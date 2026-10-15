import * as vscode from "vscode";
import { Projects, normalizedPath } from "../projects";
import type {
  DiscoveryResult,
  ElementEntry,
  PageEntry,
  TestEntry,
} from "../protocol/generated";
import { ServerManager, type Project } from "../server/serverManager";
import { LatestRefresh } from "./refresh";

export interface LocatedElement {
  project: Project;
  page: PageEntry;
  element: ElementEntry;
}
export interface LocatedTest {
  project: Project;
  test: TestEntry;
}

export class DiscoveryStore implements vscode.Disposable {
  private readonly results = new Map<string, DiscoveryResult>();
  private keys = new Set<string>();
  private readonly changed = new vscode.EventEmitter<Project>();
  readonly onDidChange = this.changed.event;
  private readonly diagnostics = vscode.languages.createDiagnosticCollection(
    "wintestkit-discovery",
  );
  private readonly refreshes: LatestRefresh<DiscoveryResult>;
  private readonly subscriptions: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    servers: ServerManager,
    log: vscode.LogOutputChannel,
  ) {
    this.refreshes = new LatestRefresh(
      async (key) => {
        const project = projects.all.find(
          (project) => project.root.toString() === key,
        );
        if (!project) throw new Error("Project was removed");
        const connection = await servers.get(project);
        const overrides: Record<string, string> = {};
        for (const document of vscode.workspace.textDocuments) {
          if (
            document.isDirty &&
            document.languageId === "python" &&
            document.uri.scheme === "file" &&
            projects.projectFor(document.uri)?.root.toString() === key
          )
            overrides[document.uri.fsPath] = document.getText();
        }
        return connection.client.request<DiscoveryResult>("discover", {
          overrides,
        });
      },
      (key, result) => {
        this.results.set(key, result);
        this.updateDiagnostics();
        const project = projects.all.find(
          (project) => project.root.toString() === key,
        );
        if (project) this.changed.fire(project);
      },
      (error) => log.error(`Discovery failed: ${String(error)}`),
    );
    const watcher = vscode.workspace.createFileSystemWatcher("**/*.py");
    const refreshFile = (uri: vscode.Uri) => {
      const project = projects.projectFor(uri);
      if (project) this.refresh(project);
    };
    this.subscriptions = [
      watcher,
      watcher.onDidCreate(refreshFile),
      watcher.onDidChange(refreshFile),
      watcher.onDidDelete(refreshFile),
      projects.onDidChange(() => this.syncProjects()),
      servers.onDidChange((project) => {
        if (servers.state(project) === "ready") this.refresh(project);
      }),
      vscode.workspace.onDidSaveTextDocument((document) =>
        refreshFile(document.uri),
      ),
      vscode.workspace.onDidCloseTextDocument((document) =>
        refreshFile(document.uri),
      ),
      vscode.workspace.onDidChangeTextDocument((event) => {
        const project = projects.projectFor(event.document.uri);
        if (project && event.document.languageId === "python")
          this.refreshes.schedule(project.root.toString(), 400);
      }),
      vscode.workspace.onDidRenameFiles((event) => {
        for (const file of event.files) {
          refreshFile(file.oldUri);
          refreshFile(file.newUri);
        }
      }),
    ];
    this.syncProjects();
  }
  private syncProjects(): void {
    const keys = new Set(
      this.projects.all.map((project) => project.root.toString()),
    );
    for (const key of this.keys)
      if (!keys.has(key)) {
        this.results.delete(key);
        this.refreshes.remove(key);
      }
    this.keys = keys;
    this.updateDiagnostics();
    for (const project of this.projects.all) this.refresh(project);
  }
  refresh(project: Project): void {
    this.refreshes.schedule(project.root.toString());
  }
  get(project: Project): DiscoveryResult | undefined {
    return this.results.get(project.root.toString());
  }
  elementAt(uri: vscode.Uri, line: number): LocatedElement | undefined {
    const project = this.projects.projectFor(uri);
    if (!project) return;
    for (const page of this.get(project)?.pages ?? []) {
      if (normalizedPath(page.file) !== normalizedPath(uri.fsPath)) continue;
      const element = page.elements.find(
        (element) =>
          element.range.start.line <= line && element.range.end.line >= line,
      );
      if (element) return { project, page, element };
    }
  }
  testAt(uri: vscode.Uri, line: number): LocatedTest | undefined {
    const project = this.projects.projectFor(uri);
    if (!project) return;
    const test = (this.get(project)?.tests ?? [])
      .filter(
        (test) =>
          normalizedPath(test.file) === normalizedPath(uri.fsPath) &&
          test.range.start.line <= line &&
          test.range.end.line >= line,
      )
      .sort(
        (first, second) => second.range.start.line - first.range.start.line,
      )[0];
    if (test) return { project, test };
  }
  pageById(id: string, project?: Project): PageEntry | undefined {
    return this.selected(project)
      .flatMap((result) => result.pages)
      .find((page) => page.id === id);
  }
  testById(id: string, project?: Project): TestEntry | undefined {
    return this.selected(project)
      .flatMap((result) => result.tests)
      .find((test) => test.id === id);
  }
  elementById(id: string, project?: Project): ElementEntry | undefined {
    return this.selected(project)
      .flatMap((result) => result.pages.flatMap((page) => page.elements))
      .find((element) => element.id === id);
  }
  private selected(project?: Project): DiscoveryResult[] {
    const result = project ? this.get(project) : undefined;
    return project ? (result ? [result] : []) : [...this.results.values()];
  }
  private updateDiagnostics(): void {
    this.diagnostics.clear();
    const files = new Map<string, vscode.Diagnostic[]>();
    for (const result of this.results.values())
      for (const error of result.errors) {
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(error.line, 0, error.line, 1),
          error.message,
          vscode.DiagnosticSeverity.Warning,
        );
        diagnostic.source = "WinTestKit discovery";
        const entries = files.get(error.file) ?? [];
        entries.push(diagnostic);
        files.set(error.file, entries);
      }
    for (const [file, diagnostics] of files)
      this.diagnostics.set(vscode.Uri.file(file), diagnostics);
  }
  dispose(): void {
    this.refreshes.dispose();
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.diagnostics.dispose();
    this.changed.dispose();
  }
}
