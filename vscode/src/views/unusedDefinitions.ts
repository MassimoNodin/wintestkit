import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { Project } from "../server/serverManager";

/** Undefined provider output means unavailable, never an empty reference list. */
export function isUnusedFromReferences(
  refs: readonly vscode.Location[] | undefined,
  uri: vscode.Uri,
  position: vscode.Position,
): boolean | undefined {
  // A real provider always reports at least the declaration. An empty list means no provider
  // answered, which must stay unknown rather than turn every definition into "unused".
  if (refs === undefined || refs.length === 0) return undefined;
  return !refs.some((ref) => ref.uri.toString() !== uri.toString() || !ref.range.contains(position));
}

/** A bounded, explicitly on-demand static estimate. Unknown is never treated as unused. */
export class UnusedDefinitions implements vscode.Disposable {
  private readonly results = new Map<string, Set<string>>();
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private run?: vscode.CancellationTokenSource;
  private readonly subscriptions: vscode.Disposable[];
  constructor(private readonly projects: Projects, private readonly discovery: DiscoveryStore) {
    this.subscriptions = [
      projects.onDidChange(() => this.invalidate()),
      discovery.onDidChange((project) => this.invalidate(project)),
      vscode.workspace.onDidChangeTextDocument((event) => {
        const project = projects.projectFor(event.document.uri);
        if (project) this.invalidate(project);
      }),
    ];
  }
  has(project: Project, elementId: string): boolean {
    return this.results.get(project.root.toString())?.has(elementId) ?? false;
  }
  hasResult(project: Project): boolean { return this.results.has(project.root.toString()); }
  get scanning(): boolean { return this.run !== undefined; }
  /** Definitions marked unused across all projects with a finished scan. */
  get count(): number {
    let total = 0;
    for (const unused of this.results.values()) total += unused.size;
    return total;
  }
  get hasResults(): boolean { return this.results.size > 0; }
  async scan(): Promise<{ cancelled: boolean; capped: boolean; unavailable: number }> {
    this.run?.cancel();
    const source = new vscode.CancellationTokenSource();
    this.run = source;
    this.changed.fire();
    let unavailable = 0;
    let capped = false;
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Finding unused definitions", cancellable: true }, async (progress, token) => {
        token.onCancellationRequested(() => source.cancel());
        const projects = [...this.projects.all];
        for (const project of projects) {
          const result = this.discovery.get(project);
          if (!result) continue;
          // A page's window and a component's root scope the page implicitly, so no reference to
          // them is expected even though they are in use.
          const entries = result.pages.flatMap((page) =>
            page.elements
              .filter((element) => element.kind !== "window" && element.name !== "root")
              .map((element) => ({ page, element })),
          );
          if (entries.length > 300) capped = true;
          const unused = new Set<string>();
          const limit = 300;
          for (const [index, { page, element }] of entries.slice(0, limit).entries()) {
            if (source.token.isCancellationRequested) break;
            progress.report({ message: `${index + 1}/${Math.min(entries.length, limit)} definitions` });
            try {
              const uri = vscode.Uri.file(page.file);
              const position = new vscode.Position(element.nameRange.start.line, element.nameRange.start.character);
              const refs = await vscode.commands.executeCommand<vscode.Location[] | undefined>("vscode.executeReferenceProvider", uri, position);
              const classification = isUnusedFromReferences(refs, uri, position);
              if (classification === true) unused.add(element.id);
              else if (classification === undefined) unavailable++;
            } catch { unavailable++; /* Provider errors leave this entry unknown. */ }
          }
          if (!source.token.isCancellationRequested && this.projects.all.some((item) => item.root.toString() === project.root.toString())) this.results.set(project.root.toString(), unused);
        }
      });
      this.changed.fire();
      return { cancelled: source.token.isCancellationRequested, capped, unavailable };
    } finally {
      if (this.run === source) this.run = undefined;
      source.dispose();
      this.changed.fire();
    }
  }
  private invalidate(project?: Project): void {
    if (project) this.results.delete(project.root.toString()); else this.results.clear();
    this.run?.cancel();
    this.changed.fire();
  }
  dispose(): void { this.run?.cancel(); this.subscriptions.forEach((item) => item.dispose()); this.changed.dispose(); }
}
