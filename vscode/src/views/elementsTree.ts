import { randomBytes } from "node:crypto";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { CheckResultsStore } from "../editor/decorations";
import { flowKey, type FlowRuns } from "../editor/flowRuns";
import type { DiscoveryResult } from "../protocol/generated";
import { buildTree, type ElementNode } from "./elementsTreeModel";
import { navigationDocument, renderBody } from "./navigationDocument";
import {
  SECTION_LABEL,
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

interface NavigationHost {
  globalState: vscode.Memento;
  workspaceState: vscode.Memento;
  extensionUri: vscode.Uri;
}

export class ElementsTree
  implements vscode.WebviewViewProvider, vscode.Disposable
{
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
      vscode.window.registerWebviewViewProvider("wintestkit.navigation", this, {
        webviewOptions: { retainContextWhenHidden: true },
      }),
      vscode.commands.registerCommand(
        "wintestkit.elements.goTo",
        (node: ElementNode) => this.openNode(node),
      ),
    ];
  }
  resolveWebviewView(view: vscode.WebviewView): void {
    if (!this.host || this.disposed) return;
    this.view = view;
    const icons = vscode.Uri.joinPath(this.host.extensionUri, "media", "codicons");
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [icons],
    };
    view.description = SECTION_LABEL[this.session.section];
    view.webview.html = this.document(view);
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    const listener = view.webview.onDidReceiveMessage((value: unknown) => {
      if (!this.disposed && this.view === view) this.onMessage(value);
    });
    this.viewSubscriptions = [
      listener,
      view.onDidDispose(() => {
        listener.dispose();
        if (this.view === view) this.view = undefined;
      }),
    ];
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
    if (effect.type === "initialize") {
      void vscode.commands.executeCommand("wintestkit.initProject");
      return;
    }
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
    this.view.description = SECTION_LABEL[payload.section];
    void this.view.webview.postMessage(payload);
  }
  private document(view: vscode.WebviewView): string {
    const payload = this.payload();
    return navigationDocument({
      cspSource: view.webview.cspSource,
      nonce: randomBytes(16).toString("hex"),
      iconsHref: view.webview
        .asWebviewUri(
          vscode.Uri.joinPath(this.host!.extensionUri, "media", "codicons", "codicon.css"),
        )
        .toString(),
      section: payload.section,
      treeHtml: payload.html,
    });
  }
  private payload(reveal = false): {
    type: "render";
    section: NavigationSection;
    html: string;
    reveal?: boolean;
  } {
    const source = this.sectionNodes();
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
        welcome: emptyMessage(this.session.section, hasProject, nodes.length),
        showInitialize: !hasProject,
      }),
    };
    return reveal ? { ...message, reveal: true } : message;
  }
}
