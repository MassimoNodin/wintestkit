import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { Project } from "../server/serverManager";
import type { DiscoveryStore } from "../discovery/store";
import type { CheckResultsStore } from "../editor/decorations";
import { flowKey, type FlowRuns } from "../editor/flowRuns";
import type { DiscoveryResult } from "../protocol/generated";
import { buildTree, type ElementNode } from "./elementsTreeModel";
import { renderBody } from "./navigationDocument";
import {
  actionsFor,
  checkPresentation,
  emptyMessage,
  findNode,
  navigationExpandedKey,
  navigationSectionKey,
  nodeContext,
  parseNavigationMessage,
  readExpanded,
  readSection,
  reduceNavigation,
  toNavNodes,
  NavigationSession,
  type NavigationAction,
  type NavigationSection,
} from "./navigationModel";
import { buildProjectTree } from "./projectTreeModel";
import type { Reports } from "../report";
import type { UnusedDefinitions } from "./unusedDefinitions";
import { annotateUnused, type UnusedLookup } from "./unusedAnnotation";
import type { UnusedToolsState } from "./navigationDocument";
import type { SetupMonitor } from "../setup/monitor";

interface NavigationHost {
  globalState: vscode.Memento;
  workspaceState: vscode.Memento;
  extensionUri: vscode.Uri;
}

/** The Pages & Flows part of the sidebar view (see `SidebarView`). */
export class ElementsTree implements vscode.Disposable {
  private readonly session: NavigationSession;
  private readonly subscriptions: vscode.Disposable[];
  private view?: vscode.WebviewView;
  private viewSubscriptions: vscode.Disposable[] = [];
  private disposed = false;
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly checks: CheckResultsStore,
    private readonly flows: FlowRuns,
    private readonly host?: NavigationHost,
    private readonly reports?: Reports,
    private readonly unused?: UnusedDefinitions,
    private readonly setup?: SetupMonitor,
  ) {
    this.session = new NavigationSession(
      readSection(host?.globalState.get(navigationSectionKey)),
      readExpanded(host?.workspaceState.get(navigationExpandedKey)),
    );
    const refresh = () => this.publish();
    this.subscriptions = [
      projects.onDidChange(refresh),
      discovery.onDidChange(refresh),
      checks.onDidChange(refresh),
      flows.onDidChange(refresh),
      ...(reports ? [reports.onDidChange(refresh)] : []),
      ...(unused ? [unused.onDidChange(refresh)] : []),
      ...(setup ? [setup.onDidChange(() => this.postFocus())] : []),
      vscode.commands.registerCommand(
        "wintestkit.elements.goTo",
        (node: ElementNode) => this.openNode(node),
      ),
      vscode.window.onDidChangeActiveTextEditor(refresh),
    ];
  }
  /** Starts publishing to the sidebar's webview, whose page the sidebar view builds. */
  attach(view: vscode.WebviewView): void {
    if (this.disposed) return;
    this.view = view;
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.viewSubscriptions = [
      view.onDidDispose(() => {
        if (this.view === view) this.view = undefined;
      }),
    ];
  }
  /** What the sidebar page shows for this part before the first update arrives. */
  initial(): { section: NavigationSection; treeHtml: string } {
    const { section, html } = this.payload();
    return { section, treeHtml: html };
  }
  /** Takes a message from the sidebar page; the ones that are not this part's are ignored. */
  handleMessage(value: unknown): void {
    if (!this.disposed) this.onMessage(value);
  }
  getChildren(node?: ElementNode, section?: NavigationSection): ElementNode[] {
    if (node) return node.children;
    return section === "flows"
      ? buildProjectTree(this.discoveries())
      : buildTree(this.discoveries());
  }
  getTreeItem(node: ElementNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      node.label,
      node.children.length
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
    );
    item.id = node.id;
    item.description = node.description;
    item.tooltip = node.tooltip ?? node.description;
    item.contextValue = nodeContext(node);
    const presentation = checkPresentation(
      node.elementId ? this.checks.results.get(node.elementId)?.status : undefined,
    );
    item.iconPath = new vscode.ThemeIcon(
      presentation?.icon ?? node.icon,
      presentation ? new vscode.ThemeColor(presentation.color) : undefined,
    );
    if (node.file)
      item.command = {
        command: "wintestkit.elements.goTo",
        title: "Go to Definition",
        arguments: [node],
      };
    return item;
  }
  dispose(): void {
    this.disposed = true;
    this.view = undefined;
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
  private discoveries(): DiscoveryResult[] {
    return this.projects.all
      .map((project) => this.discovery.get(project))
      .filter((result): result is DiscoveryResult => result !== undefined);
  }
  private sectionNodes(): ElementNode[] {
    const discoveries = this.discoveries();
    return this.session.section === "pages"
      ? buildTree(discoveries)
      : buildProjectTree(discoveries);
  }
  private onMessage(value: unknown): void {
    if (value && typeof value === "object" && (value as { type?: unknown }).type === "unusedScan") {
      if (!this.unused || this.unused.scanning) return;
      void this.unused.scan().then((summary) => {
        this.publish();
        if (summary.cancelled) void vscode.window.showInformationMessage("Unused-definition scan cancelled. Completed project results remain available.");
        else if (summary.unavailable > 0) void vscode.window.showWarningMessage(`${summary.unavailable} definition(s) could not be checked because the Python reference provider was unavailable or failed. They remain unmarked.`);
        if (summary.capped) void vscode.window.showInformationMessage("Scan limit reached: only the first 300 definitions per project were checked.");
      }).catch((error: unknown) => vscode.window.showErrorMessage(`Unused-definition scan failed: ${String(error)}`));
      return;
    }
    if (value && typeof value === "object" && (value as { type?: unknown }).type === "unusedToggle") {
      if (!this.unused?.hasResults) return;
      this.showUnused = !this.showUnused;
      this.publish();
      return;
    }
    const message = parseNavigationMessage(value);
    if (!message) return;
    const nodes = this.sectionNodes();
    const effect = reduceNavigation(this.session, nodes, message, Date.now());
    if (!effect) return;
    if (
      message.type === "select" ||
      message.type === "segmentKey" ||
      message.type === "toggle" ||
      message.type === "key"
    )
      this.persist();
    if (effect.type === "action") {
      this.showFailure(this.perform(effect.action, effect.id));
      this.publish();
      return;
    }
    if (effect.openId) {
      const node = findNode(this.sectionNodes(), effect.openId);
      if (node?.file) this.showFailure(this.openNode(node));
    }
    this.publish(effect.reveal === true);
  }
  private showUnused = false;
  private showFailure(work: Promise<void>): void {
    void work.catch((error: unknown) => {
      void vscode.window.showErrorMessage(
        error instanceof Error ? error.message : String(error),
      );
    });
  }
  private async perform(action: NavigationAction, id: string): Promise<void> {
    const node = findNode(this.sectionNodes(), id);
    if (!node || !actionsFor(node).includes(action)) return;
    if (action === "highlight" || action === "check") {
      if (!node.file || !node.qualname) return;
      await vscode.commands.executeCommand(
        action === "highlight"
          ? "wintestkit.highlightElement"
          : "wintestkit.checkElement",
        { file: node.file, qualname: node.qualname },
      );
      return;
    }
    if (action === "run") {
      if (!node.file) return;
      await vscode.commands.executeCommand("wintestkit.runFlow", {
        file: node.file,
        name: node.label,
      });
      return;
    }
    if (action === "checkPage") {
      if (!node.file || !node.page) return;
      await vscode.commands.executeCommand("wintestkit.checkPage", {
        file: node.file,
        page: node.page,
      });
      return;
    }
  }
  private async openNode(node?: ElementNode): Promise<void> {
    if (!node?.file) return;
    const location = node.range ?? {
      start: { line: 0, character: 0 },
      end: { line: 0, character: 0 },
    };
    const range = new vscode.Range(
      location.start.line,
      location.start.character,
      location.end.line,
      location.end.character,
    );
    const editor = await vscode.window.showTextDocument(vscode.Uri.file(node.file), {
      selection: range,
    });
    editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    if (node.elementId && node.qualname && node.kind !== "window") {
      const project = this.projects.projectFor(vscode.Uri.file(node.file));
      if (project)
        await vscode.commands.executeCommand("wintestkit.spy.showDefinition", {
          id: node.elementId,
          qualname: node.qualname,
          projectRoot: project.root.fsPath,
        });
    }
  }
  private persist(): void {
    if (!this.host) return;
    void this.host.globalState.update(navigationSectionKey, this.session.section);
    void this.host.workspaceState.update(navigationExpandedKey, {
      pages: [...this.session.expanded.pages],
      flows: [...this.session.expanded.flows],
    });
  }
  private publish(reveal = false): void {
    if (!this.view || this.disposed) return;
    const payload = this.payload(reveal);
    void this.view.webview.postMessage(payload);
    this.postFocus();
  }
  /** While the guided setup shows in Test Target this panel is dulled. */
  private postFocus(): void {
    if (!this.view || this.disposed || !this.setup) return;
    void this.view.webview.postMessage({ type: "tour", dim: this.setup.focus.dim });
  }
  private payload(reveal = false): {
    type: "render";
    section: NavigationSection;
    html: string;
    reveal?: boolean;
    unused?: UnusedToolsState;
  } {
    let source = this.sectionNodes();
    const unusedState = this.unusedState();
    if (unusedState) source = annotateUnused(source, this.unusedLookup(), unusedState.filtering);
    const nodes = toNavNodes(
      source,
      (elementId) =>
        elementId ? this.checks.results.get(elementId)?.status : undefined,
      (node) => {
        if (node.kind !== "flow" || !node.runnable || !node.file) return;
        const status = this.flows.states.get(
          flowKey({ file: node.file, name: node.label }),
        )?.status;
        return status;
      },
    );
    this.session.prune(nodes);
    const hasProject = this.projects.all.length > 0;
    const message = {
      type: "render" as const,
      section: this.session.section,
      html: renderBody({
        nodes,
        expanded: this.session.expanded[this.session.section],
        focusId: this.session.focus[this.session.section],
        welcome: unusedState?.filtering && nodes.length === 0
          ? undefined
          : emptyMessage(this.session.section, hasProject, nodes.length),
        notice: unusedState?.filtering && nodes.length === 0
          ? "No unused definitions found. Every scanned definition has at least one reference."
          : undefined,
      }),
      ...(unusedState ? { unused: unusedState } : {}),
    };
    return reveal ? { ...message, reveal: true } : message;
  }
  private unusedState(): UnusedToolsState | undefined {
    if (this.session.section !== "pages" || !this.unused) return undefined;
    const scanned = this.unused.hasResults;
    return {
      scanning: this.unused.scanning,
      scanned,
      count: this.unused.count,
      filtering: this.showUnused && scanned,
    };
  }
  private unusedLookup(): UnusedLookup {
    const unused = this.unused!;
    const owners = this.projects.all.flatMap((project) => {
      const root = this.discovery.get(project)?.root;
      return root === undefined ? [] : [{ project, root, prefix: root + "|" }];
    });
    const byKey = new Map(owners.map(({ project }) => [project.root.toString(), project]));
    return {
      ownerOf: (node) =>
        owners
          .find(({ root, prefix }) => node.id === root || node.id.startsWith(prefix))
          ?.project.root.toString(),
      hasResult: (key) => {
        const project = byKey.get(key);
        return project !== undefined && unused.hasResult(project);
      },
      isUnused: (key, elementId) => {
        const project = byKey.get(key);
        return project !== undefined && unused.has(project, elementId);
      },
    };
  }
  private currentProject(): Project | undefined {
    const uri = vscode.window.activeTextEditor?.document.uri;
    return (uri && this.projects.projectFor(uri)) || this.projects.all[0];
  }
}
