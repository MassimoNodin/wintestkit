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
import { readConfiguration } from "../settings/files";
import {
  DEFAULT_KEEP_RUNS,
  RUN_CONTEXT_PREFIX,
  runDirectory,
} from "../runHistory";
import { runArguments, runProcess, replaysByDefault } from "./runner";
import { runDebugSession } from "./debug";
import type { Reports } from "../report";
import { disposeRunProfiles } from "./profiles";
import { offerDoctorForRun } from "./environment";
import { appendRelocationAction } from "./failureActions";
import { saveExecutionSources } from "./saveSources";

interface ItemData {
  project: Project;
  nodeid?: string;
}
export function failureMessages(
  end?: TestEnd,
  fallback?: string,
  runName?: string,
): vscode.TestMessage[] {
  const text = end?.message ?? end?.error?.message ?? fallback ?? "Test failed";
  const markdown = new vscode.MarkdownString();
  markdown.appendText(text);
  if (end?.error?.diagnostic) {
    markdown.appendMarkdown("\n\n");
    markdown.appendCodeblock(formatDiagnostic(end.error.diagnostic), "text");
    appendRelocationAction(markdown, end.error.diagnostic);
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
  if (runName)
    for (const each of messages)
      each.contextValue = RUN_CONTEXT_PREFIX + runName;
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
  private readonly activeRunNames = new Set<string>();
  private reportContextVersion = 0;
  private readonly subscriptions: vscode.Disposable[];
  private readonly profile: vscode.TestRunProfile;
  private readonly debugProfile: vscode.TestRunProfile;
  private readonly recordingProfile: vscode.TestRunProfile;
  private disposed = false;
  private rebuildPending = false;
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly log: vscode.LogOutputChannel,
    private readonly reports: Reports,
    private readonly attachFailures?: {
      /** A run is starting, so an earlier attach failure no longer describes the app. */
      cleared(project: Project): void;
      /** A test could not start because attach mode found the app not running. */
      notRunning(project: Project): void;
    },
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
      reports.onDidChange(() => { void this.refreshReportContexts(); }),
    ];
    this.rebuild();
  }
  private key(project: Project, nodeid: string): string {
    return project.root.fsPath + "|" + nodeid;
  }
  private rebuild(): void {
    if (this.active.size) {
      this.rebuildPending = true;
      return;
    }
    this.rebuildPending = false;
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
    void this.refreshReportContexts();
  }
  private async refreshReportContexts(): Promise<void> {
    const version = ++this.reportContextVersion;
    const projects = await Promise.all(this.projects.all.map(async (project) =>
      [project.root.toString(), await this.reports.reportedTestIds(project)] as const));
    if (this.disposed || version !== this.reportContextVersion) return;
    const available = new Map(projects);
    const reportItems: string[] = [];
    for (const item of this.items.values()) {
      const data = this.metadata.get(item);
      const nodeid = data?.nodeid;
      const ids = data && available.get(data.project.root.toString());
      if (nodeid && ids && [...ids].some((id) =>
        id === nodeid || id.startsWith(nodeid + "::") || id.startsWith(nodeid + "[")))
        reportItems.push(item.id);
    }
    await vscode.commands.executeCommand("setContext", "wintestkit.reportTestIds", reportItems);
    if (this.disposed || version !== this.reportContextVersion) return;
    const reported = new Set(reportItems);
    for (const item of this.items.values()) {
      const hasReport = reported.has(item.id);
      const tagId = "wintestkit.reportAvailable";
      if (item.tags.some((tag) => tag.id === tagId) !== hasReport)
        item.tags = hasReport
          ? [...item.tags, new vscode.TestTag(tagId)]
          : item.tags.filter((tag) => tag.id !== tagId);
    }
  }
  prepareClearResults(): () => Promise<void> {
    const projects = [...this.projects.all];
    const roots = projects.map((project) => project.root.toString());
    const names = this.reports.history.all()
      .filter((entry) => !this.activeRunNames.has(entry.name))
      .map((entry) => entry.name);
    return async () => {
      await Promise.all(names.map((name) => this.reports.history.discard(name, roots)));
      this.reports.clearLastRuns(projects);
      const cleared = new Set(names.map((name) => RUN_CONTEXT_PREFIX + name));
      for (const [id, messages] of this.lastMessages)
        if (messages.some((message) => message.contextValue && cleared.has(message.contextValue)))
          this.lastMessages.delete(id);
      await this.refreshReportContexts();
    };
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
    // Each run gets a unique name so a button on one of its test rows can tell VS Code's history
    // which run it belongs to; debug runs write no report and need none.
    const selected = this.selected(request);
    const name = debug ? undefined : this.reports.history.newName();
    const run = this.controller.createTestRun(request, name);
    if (name) this.activeRunNames.add(name);
    if (name)
      run.onDidDispose(() => {
        if (this.disposed) return;
        this.reports.clearRun(name);
        this.reports.history
          .discard(name)
          .catch((error) => this.log.warn(String(error)));
      });
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
        [...selected].map(([project, items]) => {
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
      if (name) this.activeRunNames.delete(name);
      if (!this.disposed && !this.active.size && this.rebuildPending) this.rebuild();
      for (const project of selected.keys()) {
        const keep = vscode.workspace.getConfiguration("wintestkit", project.root)
          .get<number>("keepRunReports", DEFAULT_KEEP_RUNS);
        await this.reports.history.prune(keep, this.activeRunNames)
          .catch((error) => this.log.warn(String(error)));
      }
      await this.refreshReportContexts();
    }
  }
  private apply(
    project: Project,
    run: vscode.TestRun,
    actions: RunAction[],
  ): void {
    for (const action of actions) {
      if (action.kind === "report") {
        this.reports.record(project, action.path, action.failed, action.passed, run.name);
        this.reports.history.finish(run.name, project.root.toString(), {
          failed: action.failed,
          passed: action.passed,
        });
        run.appendOutput(
          `Last run: ${action.passed} passed, ${action.failed} failed${action.path ? " · Open Last Report from the WinTestKit status menu" : ""}\r\n`,
        );
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
        if (action.end?.error?.type === "AttachNotRunningError")
          this.attachFailures?.notRunning(project);
        const messages = failureMessages(action.end, action.message, run.name);
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

  reportTarget(item: vscode.TestItem): ItemData | undefined {
    const known = this.items.get(item.id);
    const data = this.metadata.get(item) ?? (known && this.metadata.get(known));
    if (data) return data;
    for (const project of this.projects.all) {
      const prefix = this.key(project, "");
      if (item.id.startsWith(prefix)) return { project, nodeid: item.id.slice(prefix.length) || undefined };
    }
    return undefined;
  }
  /** Gives this run its own report folder, so earlier runs keep theirs. */
  private async startRunReport(
    project: Project,
    name: string | undefined,
    settings: vscode.WorkspaceConfiguration,
  ): Promise<string | undefined> {
    if (!name) return undefined;
    const config = await readConfiguration(project.root).catch(
      () => ({}) as Record<string, unknown>,
    );
    const configured =
      typeof config.report_dir === "string" && config.report_dir
        ? config.report_dir
        : "wtk-report";
    const dir = runDirectory(project.root.fsPath, configured, name);
    this.reports.history.start(
      name,
      project.root.toString(),
      project.name,
      dir,
    );
    const keep = settings.get<number>("keepRunReports", DEFAULT_KEEP_RUNS);
    void this.reports.history
      .prune(keep, this.activeRunNames)
      .catch((error) => this.log.warn(String(error)));
    return dir;
  }
  private async runProject(
    project: Project,
    items: vscode.TestItem[],
    run: vscode.TestRun,
    token: vscode.CancellationToken,
    debug = false,
    recording = false,
  ): Promise<void> {
    this.attachFailures?.cleared(project);
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
      if (!(await saveExecutionSources(this.projects, project))) {
        this.apply(project, run, mapper.finish(null, true));
        return;
      }
      if (token.isCancellationRequested || this.disposed) {
        this.apply(project, run, mapper.finish(null, true));
        return;
      }
      if (!python) throw new Error("Select a Python interpreter first.");
      const url = await listener.listen();
      const settings = vscode.workspace.getConfiguration(
        "wintestkit",
        project.root,
      );
      const extraArgs = settings.get<string[]>("run.extraArgs", []);
      const reportDir = debug
        ? undefined
        : await this.startRunReport(project, run.name, settings);
      const args = runArguments(
        url,
        nodeids,
        settings.get<boolean>("run.highlightActions", false),
        extraArgs,
        recording,
        replaysByDefault(
          await readConfiguration(project.root, {}, false).catch(() => ({
            replay: undefined,
          })),
          extraArgs,
        ),
        reportDir,
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
      if (!token.isCancellationRequested)
        await offerDoctorForRun(
          code,
          project,
          (message, action) => vscode.window.showWarningMessage(message, action),
          (command, target) => vscode.commands.executeCommand(command, target),
        );
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
    disposeRunProfiles(this.profile, this.debugProfile, this.recordingProfile);
    this.controller.dispose();
  }
}
