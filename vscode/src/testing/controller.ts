import * as path from "node:path";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import { formatDiagnostic } from "../editor/diagnostics";
import { getInterpreter } from "../python";
import type { Project } from "../server/serverManager";
import type { TestEntry } from "../protocol/generated";
import { EventMapper, type RunAction, type TestEnd } from "./eventMapper";
import { EventServer } from "./eventServer";
import { runArguments, runProcess } from "./runner";
import { runDebugSession } from "./debug";
import type { Reports } from "../report";

interface ItemData {
  project: Project;
  nodeid?: string;
}
export function failureMessages(
  end?: TestEnd,
  fallback?: string,
): vscode.TestMessage[] {
  const text = end?.message ?? end?.error?.message ?? fallback ?? "Test failed";
  const markdown = new vscode.MarkdownString();
  markdown.appendText(text);
  if (end?.error?.diagnostic) {
    markdown.appendMarkdown("\n\n");
    markdown.appendCodeblock(formatDiagnostic(end.error.diagnostic), "text");
    const relocation = end.error.diagnostic.relocations?.[0];
    if (relocation) {
      const args = encodeURIComponent(JSON.stringify([relocation.path]));
      markdown.appendMarkdown(
        "\n\n[Reveal relocated element in Spy](command:wintestkit.spy.revealRelocation?" +
          args +
          ")",
      );
      markdown.isTrusted = {
        enabledCommands: ["wintestkit.spy.revealRelocation"],
      };
    }
  }
  for (const screenshot of end?.screenshots ?? []) {
    markdown.appendMarkdown(
      "\n\n[" +
        path.basename(screenshot).replace(/[\[\]]/g, "") +
        "](" +
        vscode.Uri.file(screenshot).toString() +
        ")",
    );
  }
  const message = new vscode.TestMessage(markdown);
  if (end?.location)
    message.location = new vscode.Location(
      vscode.Uri.file(end.location.file),
      new vscode.Position(end.location.line, 0),
    );
  const messages = [message];
  const expected = /^Expected:\s*(.*)$/im.exec(text)?.[1];
  const actual = /^Actual:\s*(.*)$/im.exec(text)?.[1];
  if (expected !== undefined && actual !== undefined) {
    const diff = vscode.TestMessage.diff(
      "Assertion mismatch",
      expected,
      actual,
    );
    diff.location = message.location;
    messages.push(diff);
  }
  return messages;
}

export class TestController implements vscode.Disposable {
  readonly controller = vscode.tests.createTestController(
    "wintestkit",
    "WinTestKit",
  );
  readonly lastMessages = new Map<string, vscode.TestMessage[]>();
  readonly items = new Map<string, vscode.TestItem>();
  private readonly metadata = new WeakMap<vscode.TestItem, ItemData>();
  private readonly queues = new Map<string, Promise<void>>();
  private readonly active = new Set<vscode.CancellationTokenSource>();
  private readonly subscriptions: vscode.Disposable[];
  private readonly profile: vscode.TestRunProfile;
  private readonly debugProfile: vscode.TestRunProfile;
  private readonly recordingProfile: vscode.TestRunProfile;
  private disposed = false;
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly log: vscode.LogOutputChannel,
    private readonly reports: Reports,
  ) {
    this.profile = this.controller.createRunProfile(
      "Run",
      vscode.TestRunProfileKind.Run,
      (request, token) => this.run(request, token),
      true,
    );
    this.debugProfile = this.controller.createRunProfile(
      "Debug (no report)",
      vscode.TestRunProfileKind.Debug,
      (request, token) => this.run(request, token, true),
      true,
    );
    this.recordingProfile = this.controller.createRunProfile(
      "Run with recording",
      vscode.TestRunProfileKind.Run,
      (request, token) => this.run(request, token, false, true),
      false,
    );
    this.controller.refreshHandler = async () => {
      await projects.refresh();
      for (const project of projects.all) discovery.refresh(project);
    };
    this.subscriptions = [
      discovery.onDidChange(() => this.rebuild()),
      projects.onDidChange(() => this.rebuild()),
    ];
    this.rebuild();
  }
  private key(project: Project, nodeid: string): string {
    return project.root.fsPath + "|" + nodeid;
  }
  private rebuild(): void {
    const old = new Map(this.items);
    this.items.clear();
    const roots: vscode.TestItem[] = [];
    for (const project of this.projects.all) {
      const data = this.discovery.get(project);
      if (!data) continue;
      const files = new Map<string, vscode.TestItem>();
      const entries = new Map<string, vscode.TestItem>();
      for (const test of data.tests) {
        const nodeid = path
          .relative(project.root.fsPath, test.file)
          .replaceAll("\\", "/");
        if (!files.has(test.file)) {
          const key = this.key(project, nodeid);
          const item =
            old.get(key) ??
            this.controller.createTestItem(
              key,
              nodeid,
              vscode.Uri.file(test.file),
            );
          item.children.replace([]);
          files.set(test.file, item);
          this.items.set(key, item);
          this.metadata.set(item, { project, nodeid });
        }
        const key = this.key(project, test.id);
        const item =
          old.get(key) ??
          this.controller.createTestItem(
            key,
            test.name,
            vscode.Uri.file(test.file),
          );
        item.label = test.name;
        item.range = this.range(test);
        item.children.replace([]);
        entries.set(test.id, item);
        this.items.set(key, item);
        this.metadata.set(item, { project, nodeid: test.id });
      }
      for (const test of data.tests) {
        const parent =
          (test.parent && entries.get(test.parent)) || files.get(test.file);
        const item = entries.get(test.id);
        if (parent && item) parent.children.add(item);
      }
      if (this.projects.all.length > 1) {
        const key = this.key(project, "");
        const root =
          old.get(key) ??
          this.controller.createTestItem(
            key,
            vscode.workspace.asRelativePath(project.root, true),
            project.root,
          );
        root.children.replace([...files.values()]);
        this.metadata.set(root, { project });
        this.items.set(key, root);
        roots.push(root);
      } else roots.push(...files.values());
    }
    this.controller.items.replace(roots);
  }
  private range(test: TestEntry): vscode.Range {
    return new vscode.Range(
      test.range.start.line,
      test.range.start.character,
      test.range.end.line,
      test.range.end.character,
    );
  }
  private selected(
    request: vscode.TestRunRequest,
  ): Map<Project, vscode.TestItem[]> {
    const result = new Map<Project, vscode.TestItem[]>();
    const seen = new Set<string>();
    const excluded = new Set(request.exclude?.map((item) => item.id));
    const visit = (item: vscode.TestItem): void => {
      if (excluded.has(item.id) || seen.has(item.id)) return;
      for (let parent = item.parent; parent; parent = parent.parent) {
        if (excluded.has(parent.id)) return;
      }
      seen.add(item.id);
      if (item.children.size) {
        item.children.forEach(visit);
        return;
      }
      const data = this.metadata.get(item);
      if (!data?.nodeid) return;
      const list = result.get(data.project) ?? [];
      list.push(item);
      result.set(data.project, list);
    };
    if (request.include) request.include.forEach(visit);
    else this.controller.items.forEach(visit);
    return result;
  }
  async run(
    request: vscode.TestRunRequest,
    token: vscode.CancellationToken,
    debug = false,
    recording = false,
  ): Promise<void> {
    const run = this.controller.createTestRun(request);
    const cancellation = new vscode.CancellationTokenSource();
    this.active.add(cancellation);
    const subscriptions = [
      token.onCancellationRequested(() => cancellation.cancel()),
      run.token.onCancellationRequested(() => cancellation.cancel()),
    ];
    if (
      token.isCancellationRequested ||
      run.token.isCancellationRequested ||
      this.disposed
    )
      cancellation.cancel();
    try {
      await Promise.all(
        [...this.selected(request)].map(([project, items]) => {
          items.forEach((item) => run.enqueued(item));
          const key = project.root.toString();
          const previous = this.queues.get(key) ?? Promise.resolve();
          const queued = previous
            .catch(() => {})
            .then(() =>
              this.runProject(project, items, run, cancellation.token, debug, recording),
            );
          this.queues.set(key, queued);
          return queued.finally(() => {
            if (this.queues.get(key) === queued) this.queues.delete(key);
          });
        }),
      );
    } finally {
      subscriptions.forEach((subscription) => subscription.dispose());
      this.active.delete(cancellation);
      cancellation.dispose();
      run.end();
    }
  }
  private apply(
    project: Project,
    run: vscode.TestRun,
    actions: RunAction[],
  ): void {
    for (const action of actions) {
      if (action.kind === "report") {
        this.reports.record(project, action.path, action.failed);
        run.appendOutput(`Last run: ${action.passed} passed, ${action.failed} failed${action.path ? " · Open Last Report from the WinTestKit status menu" : ""}\r\n`);
        continue;
      }
      const key = action.id && this.key(project, action.id);
      let item = key ? this.items.get(key) : undefined;
      if (!item && action.kind === "errored")
        item = this.items.get(
          this.key(
            project,
            path.relative(project.root.fsPath, action.id).replaceAll("\\", "/"),
          ),
        );
      if (action.kind === "createChild") {
        const file =
          action.test?.file ??
          path.resolve(project.root.fsPath, action.id.split("::")[0]);
        item = this.controller.createTestItem(
          this.key(project, action.id),
          action.test?.name ?? action.id.split("::").at(-1) ?? action.id,
          vscode.Uri.file(file),
        );
        if (action.test)
          item.range = new vscode.Range(
            action.test.line,
            0,
            action.test.line,
            0,
          );
        const parent =
          action.parent && this.items.get(this.key(project, action.parent));
        if (parent) parent.children.add(item);
        else {
          const fileItem = this.items.get(
            this.key(
              project,
              path.relative(project.root.fsPath, file).replaceAll("\\", "/"),
            ),
          );
          if (fileItem) fileItem.children.add(item);
          else this.controller.items.add(item);
        }
        this.items.set(item.id, item);
        this.metadata.set(item, { project, nodeid: action.id });
        continue;
      }
      if (action.kind === "output") {
        run.appendOutput(action.text, undefined, item);
        continue;
      }
      if (!item) {
        if (action.kind === "errored")
          run.appendOutput((action.message ?? "Collection error") + "\r\n");
        continue;
      }
      if (action.kind === "enqueue") run.enqueued(item);
      else if (action.kind === "started") run.started(item);
      else if (action.kind === "skipped") run.skipped(item);
      else if (action.kind === "passed") run.passed(item, action.duration);
      else if (action.kind === "failed" || action.kind === "errored") {
        const messages = failureMessages(action.end, action.message);
        this.lastMessages.set(action.id, messages);
        if (action.kind === "failed")
          run.failed(item, messages, action.duration);
        else run.errored(item, messages, action.duration);
      }
      if (
        action.kind === "passed" ||
        action.kind === "failed" ||
        action.kind === "errored" ||
        action.kind === "skipped"
      ) {
        if (action.kind === "passed" || action.kind === "skipped")
          this.lastMessages.delete(action.id);
      }
    }
  }
  private async runProject(
    project: Project,
    items: vscode.TestItem[],
    run: vscode.TestRun,
    token: vscode.CancellationToken,
    debug = false,
    recording = false,
  ): Promise<void> {
    const nodeids = items.map((item) => this.metadata.get(item)!.nodeid!);
    const mapper = new EventMapper(nodeids);
    let ended!: () => void;
    const sessionEnded = new Promise<void>((resolve) => {
      ended = resolve;
    });
    const listener = new EventServer(
      (event) => {
        this.apply(project, run, mapper.consume(event));
        if (event.event === "session_end") ended();
      },
      (error) => {
        this.log.error(String(error));
        run.appendOutput(String(error) + "\r\n");
      },
    );
    try {
      if (token.isCancellationRequested || this.disposed) {
        this.apply(project, run, mapper.finish(null, true));
        return;
      }
      const python = await getInterpreter(project.root);
      if (!python) throw new Error("Select a Python interpreter first.");
      const url = await listener.listen();
      const settings = vscode.workspace.getConfiguration(
        "wintestkit",
        project.root,
      );
      const args = runArguments(
        url,
        nodeids,
        settings.get<boolean>("run.highlightActions", false),
        settings.get<string[]>("run.extraArgs", []),
        recording,
      );
      const code = debug
        ? await runDebugSession(
            project,
            python,
            url,
            nodeids,
            run,
            token,
            sessionEnded,
          )
          : await runProcess(project, python, args, token, (text) =>
            run.appendOutput(text),
          );
      if (code === 3 && !token.isCancellationRequested) {
        const choice = await vscode.window.showWarningMessage(
          "WinTestKit's environment checks blocked this run.",
          "Check Environment",
        );
        if (choice)
          await vscode.commands.executeCommand("wintestkit.runDoctor");
      }
      await listener.drain();
      this.apply(
        project,
        run,
        mapper.finish(code, token.isCancellationRequested),
      );
    } catch (error) {
      this.log.error(String(error));
      run.appendOutput(String(error) + "\r\n");
      for (const item of items)
        run.errored(item, new vscode.TestMessage(String(error)));
    } finally {
      listener.dispose();
    }
  }
  dispose(): void {
    this.disposed = true;
    this.active.forEach((source) => source.cancel());
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.controller.dispose();
  }
}
