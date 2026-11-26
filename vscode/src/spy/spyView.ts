import { CompatibilityError, UPGRADE_LABEL } from "../compatibility";
import { ManagedPanel } from "./managedPanel";
import { SpyTrace } from "./trace";
import { isManagedNodeId, isManagedSource, ManagedInspector } from "./managedSession";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import { ServerManager, type Project } from "../server/serverManager";
import { JsonRpcClient, RpcError } from "../server/jsonrpc";
import type {
  AppStatusResult,
  DefinitionMatch,
  InspectChildrenResult,
  ManagedProcessIdentity,
  InspectCoverageResult,
  InspectDefinitionsResult,
  InspectPropertiesResult,
  InspectRefreshResult,
  NodeInfo,
  SpyHoverNotification,
  SpyPickedNotification,
  Suggestion,
} from "../protocol/generated";
import {
  BASIC_SETTING,
  DEFAULT_BASIC_PROPERTIES,
  MAX_BASIC_PROPERTIES,
  basicUiaNames,
  normalizeBasicProperties,
} from "./basicProperties";
import {
  MAX_TREE_WIDTH,
  MIN_TREE_WIDTH,
  parseSpyRequest,
  type SpyRequest,
  type SpyResponse,
} from "./messages";
import type { SetupMonitor } from "../setup/monitor";
import { readApplicationIcons } from "./appIcons";
import { livePreviewImages } from "./objectPreviews";
import { PreviewViewer } from "./previewViewer";
import { bestMatch, matchManagedIdentity, describeSegment, parseSelectionPath, processSegment, segmentOf, type PathSegment } from "./selectionPath";
import * as path from "node:path";

/** The only requests the Properties side panel may send; it mirrors the tree and must never drive it. */
const PROPERTIES_REQUESTS: ReadonlySet<string> = new Set(["copy", "basicProperty", "resetBasicProperties", "generateLocator", "openPreview", "retryPreview", "showProperties", "tour", "select", "openDefinition", "upgradePackage"]);
const PROPERTIES_HISTORY_LIMIT = 2000;
// 2 s, 4 s, 8 s, then every 10 s: about two minutes in all.
const DETAILS_RETRY_LIMIT = 13;

type SpyConnection = { client?: JsonRpcClient; revision: number };

export class SpyView implements vscode.WebviewViewProvider, vscode.Disposable {
  private readonly trace = new SpyTrace();
  private view?: vscode.WebviewView;
  private propertiesView?: vscode.WebviewView;
  private propertiesSubscriptions: vscode.Disposable[] = [];
  private propertiesReady = false;
  // Auto-reveal bookkeeping for the right sidebar. VS Code only creates that webview once it is shown, and a
  // collapsed secondary sidebar never resolves it, so Spy reveals it once itself, without keeping the focus.
  private propertiesRevealed = false;
  private propertiesRevealing?: Promise<void>;
  private propertiesWasVisible = false;
  private propertiesShowRequested = false;
  /** The user hid or closed the sidebar after seeing it, so Spy must leave it alone until they show it again. */
  private propertiesDismissed = false;
  private propertiesHistory: SpyResponse[] = [];
  private currentPreview?: Extract<SpyResponse, { type: "objectPreview" }>;
  private currentTour?: Extract<SpyResponse, { type: "tour" }>;
  private previewRevision = 0;
  private managedSnapshot?: unknown;
  private extrasActive = false;
  private tutorialEpoch = 0;
  private tutorialPrepared = false;
  private tutorialSnapshot: SpyResponse[] = [];
  private tutorialError?: string;
  private tutorialPreparation?: Promise<void>;
  private client?: JsonRpcClient;
  private project?: Project;
  private picking = false;
  private appRunning = false;
  private targetName?: string;
  private appName?: string;
  /** The selected object's route from its root window, kept so a reload can select it again. */
  private selectionPath?: PathSegment[];
  private selectionProject?: string;
  /** Set for the one refresh that follows a change of scope: that is not a reload of the same view. */
  private skipRestore = false;
  /** Set when toggling Show Other Apps with an object selected: it is selected again if its process is still listed. */
  private restoreIfListed = false;
  /** The object the webview shows details for, which a requested locator must belong to. */
  private selectedNodeId?: string;
  private pickedPoint?: { x: number; y: number; nodeId: string };
  private readonly previewViewer = new PreviewViewer();
  /** Whether the tree on screen was read from the current project and is still usable. */
  private loaded = false;
  private appPids: number[] = [];
  private showOtherApps = true;
  private treeProcesses = new Map<string, ManagedProcessIdentity>();
  private disconnectedProcess?: { project: string; process: ManagedProcessIdentity };
  private treeTokens = new Map<string, string>();
  private revision = 0;
  private scopeRevision = 0;
  private selection = 0;
  private managedInspector?: ManagedInspector;
  diagnostics(): unknown { return { visible: this.view?.visible ?? false, managedState: this.managedInspector?.state ?? "not active", lastFailure: this.managedInspector?.failure }; }
  private managedPanel?: ManagedPanel;
  private pickRevision = 0;
  private pickSession?: string;
  private refreshing?: Promise<void>;
  private refreshKey?: string;
  private coveragePending = new Set<string>();
  private coverageWorker?: { generation: number; promise: Promise<void> };
  private taskId = 0;
  private connecting?: {
    root: string;
    scopeRevision: number;
    promise: Promise<SpyConnection>;
  };
  private disposed = false;
  private suggestion?: Suggestion;
  private generatingLocatorFor?: number;
  // The definitions last shown for the selected object, so the panel can ask to open one by id.
  private definitionTargets = new Map<string, DefinitionMatch>();
  // Tree nodes the panel currently shows, so markers can be refreshed after a page file is saved.
  private loadedNodeIds = new Set<string>();
  private coverageRun = 0;
  private coverageTimer?: NodeJS.Timeout;
  private keepaliveTimer?: NodeJS.Timeout;
  private processTimer?: NodeJS.Timeout;
  private rootNodes: NodeInfo[] = [];
  private retryTimer?: NodeJS.Timeout;
  private retryRunning = false;
  private retryWanted = false;
  private managedRetryNeeded = false;
  private treeRetryNeeded = false;
  private detailsBusy = false;
  private retryGeneration = 0;
  private retryAttempt = 0;
  private recovering = false;
  private expandedPaths: PathSegment[][] = [];
  private recoveryAttempts = new Map<string, number>();
  private recoveryFailures = new Set<string>();
  private recoveryProcess?: ManagedProcessIdentity;
  private notifications: vscode.Disposable[] = [];
  private viewSubscriptions: vscode.Disposable[] = [];
  private readonly subscriptions: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    private readonly servers: ServerManager,
    private readonly extensionUri: vscode.Uri,
    private readonly log: vscode.LogOutputChannel,
    private readonly setup?: SetupMonitor,
    private readonly memory?: vscode.Memento,
  ) {
    this.subscriptions = [
      ...(setup ? [setup.onDidChange(() => this.syncTour())] : []),
      // Keep the tree when the panel tab is hidden: a recreated webview would reload everything.
      vscode.window.registerWebviewViewProvider("wintestkit.spy", this, {
        webviewOptions: { retainContextWhenHidden: true },
      }),
      vscode.window.registerWebviewViewProvider("wintestkit.properties", { resolveWebviewView: (view) => this.resolvePropertiesView(view) }, { webviewOptions: { retainContextWhenHidden: true } }),
      vscode.commands.registerCommand("wintestkit.spy.startPick", async () => {
        await vscode.commands.executeCommand("wintestkit.spy.focus");
        await this.safe(() => this.startPick());
      }),
      vscode.commands.registerCommand("wintestkit.spy.refresh", () =>
        this.safe(() => this.refresh()),
      ),
      vscode.commands.registerCommand("wintestkit.spy.resetBasicProperties", () =>
        this.safe(() => this.resetBasicProperties()),
      ),
      vscode.commands.registerCommand(
        "wintestkit.spy.revealRelocation",
        (path: string) => this.safe(() => this.revealRelocation(path)),
      ),
      projects.onDidChange(() => {
        if (this.view?.visible) void this.safe(() => this.refreshIfStale());
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("wintestkit.spy.traceFile")) this.configureTrace();
        if (
          event.affectsConfiguration("wintestkit.spy.bringWindowToFront") ||
          event.affectsConfiguration("wintestkit.spy." + BASIC_SETTING)
        )
          this.state();
      }),
      vscode.workspace.onDidSaveTextDocument((document) => {
        if (document.languageId === "python") this.scheduleCoverage();
      }),
      vscode.window.onDidChangeActiveTextEditor(() => {
        if (
          this.view?.visible &&
          this.currentProject()?.root.toString() !==
            this.project?.root.toString()
        )
          void this.safe(() => this.refresh());
      }),
      servers.onDidChange((project) => {
        if (project.root.toString() !== this.currentProject()?.root.toString())
          return;
        if (this.client) this.unbind();
        if (this.view?.visible && servers.state(project) === "ready") {
          void this.safe(async () => {
            const pending = this.refreshing ?? this.connecting?.promise;
            await pending?.catch(() => undefined);
            if (!this.disposed && this.view?.visible) await this.refresh();
          });
        }
      }),
    ];
  }
  private configureTrace(): void {
    this.trace.configure(vscode.workspace.getConfiguration("wintestkit.spy").get<string>("traceFile", ""));
  }
  async resolveWebviewView(view: vscode.WebviewView): Promise<void> {
    this.configureTrace();
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.view = view;
    this.loaded = false; // a new webview starts empty
    if (this.tutorialActive()) this.extrasActive = true;
    const assets = vscode.Uri.joinPath(this.extensionUri, "media", "spy");
    const icons = vscode.Uri.joinPath(this.extensionUri, "media", "codicons");
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [assets, icons],
    };
    const nonce = randomBytes(24).toString("hex");
    let html = await readFile(
      vscode.Uri.joinPath(assets, "spy.html").fsPath,
      "utf8",
    );
    for (const [name, value] of Object.entries({
      viewClass: "spy-view",
      cspSource: view.webview.cspSource,
      nonce,
      css: view.webview
        .asWebviewUri(vscode.Uri.joinPath(assets, "spy.css"))
        .toString(),
      treeLabelsJs: view.webview.asWebviewUri(vscode.Uri.joinPath(assets, "treeLabels.js")).toString(),
      js: view.webview
        .asWebviewUri(vscode.Uri.joinPath(assets, "spy.js"))
        .toString(),
      icons: view.webview
        .asWebviewUri(vscode.Uri.joinPath(icons, "codicon.css"))
        .toString(),
    }))
      html = html.replaceAll("{{" + name + "}}", value);
    if (this.disposed || this.view !== view) return;
    view.webview.html = html;
    this.updateKeepalive();
    if (view.visible) void this.revealProperties();
    this.viewSubscriptions = [
      view.webview.onDidReceiveMessage((value) => {
        const message = parseSpyRequest(value);
        if (message) {
          if (message.type !== "managedInvoke") this.trace.message("toHost", message);
          void this.safe(() => this.handle(message));
        }
      }),
      view.onDidChangeVisibility(() => {
        this.updateKeepalive();
        if (view.visible) {
          void this.revealProperties();
          void this.safe(() =>
            this.tutorialActive() ? this.restoreTutorial() : this.refreshIfStale(),
          );
        } else void this.safe(() => this.stopPick());
      }),
      view.onDidDispose(() => {
        if (this.view !== view) return;
        this.view = undefined;
        this.updateKeepalive();
        void this.safe(() => this.stopPick());
      }),
    ];
  }
  private async resolvePropertiesView(view: vscode.WebviewView): Promise<void> {
    this.propertiesSubscriptions.forEach((subscription) => subscription.dispose());
    this.propertiesView = view;
    this.propertiesReady = false;
    this.propertiesShowRequested = false;
    this.propertiesDismissed = false;
    this.propertiesWasVisible = view.visible;
    this.postPropertiesVisibility();
    const assets = vscode.Uri.joinPath(this.extensionUri, "media", "spy");
    const icons = vscode.Uri.joinPath(this.extensionUri, "media", "codicons");
    view.webview.options = { enableScripts: true, localResourceRoots: [assets, icons] };
    const nonce = randomBytes(24).toString("hex");
    let html = await readFile(vscode.Uri.joinPath(assets, "spy.html").fsPath, "utf8");
    for (const [name, value] of Object.entries({
      viewClass: "properties-view", cspSource: view.webview.cspSource, nonce,
      css: view.webview.asWebviewUri(vscode.Uri.joinPath(assets, "spy.css")).toString(),
      treeLabelsJs: view.webview.asWebviewUri(vscode.Uri.joinPath(assets, "treeLabels.js")).toString(),
      js: view.webview.asWebviewUri(vscode.Uri.joinPath(assets, "spy.js")).toString(),
      icons: view.webview.asWebviewUri(vscode.Uri.joinPath(icons, "codicon.css")).toString(),
    })) html = html.replaceAll("{{" + name + "}}", value);
    if (this.disposed || this.propertiesView !== view) return;
    this.propertiesSubscriptions = [
      view.webview.onDidReceiveMessage((value) => {
        const message = parseSpyRequest(value);
        if (!message) return;
        if (message.type === "propertiesReady") {
          this.propertiesReady = true;
          if (this.currentTour) void view.webview.postMessage(this.currentTour);
          for (const item of this.propertiesHistory) void view.webview.postMessage(item);
          if (this.currentPreview) void view.webview.postMessage(this.currentPreview);
          if (this.managedSnapshot) void view.webview.postMessage(this.managedSnapshot);
        } else if (message.type.startsWith("managed") || PROPERTIES_REQUESTS.has(message.type)) void this.safe(() => this.handle(message));
      }),
      view.onDidChangeVisibility(() => {
        this.propertiesShowRequested = false;
        if (view.visible) { this.propertiesWasVisible = true; this.propertiesDismissed = false; }
        else if (this.propertiesWasVisible && !this.propertiesRevealing) this.propertiesDismissed = true;
        this.postPropertiesVisibility(); this.updateKeepalive();
      }),
      view.onDidDispose(() => {
        if (this.propertiesView !== view) return;
        this.propertiesDismissed = true;
        this.propertiesView = undefined;
        this.updateKeepalive();
        this.propertiesReady = false;
        this.postPropertiesVisibility();
      }),
    ];
    view.webview.html = html;
    this.updateKeepalive();
  }
  /**
   * Makes the Properties view exist and be visible without taking the focus from Spy. A view VS Code never
   * resolved is created once through its focus command, followed by focusing Spy again; a resolved but hidden
   * one is shown with the focus preserved, once per hidden period. Nothing happens after the user hid it.
   */
  private async revealProperties(): Promise<void> {
    if (this.disposed || this.tutorialActive() || this.propertiesDismissed || this.propertiesRevealing) return;
    const existing = this.propertiesView;
    if (existing) {
      if (existing.visible || this.propertiesShowRequested) return;
      this.propertiesShowRequested = true;
      existing.show?.(true);
      return;
    }
    if (this.propertiesRevealed) return;
    this.propertiesRevealed = true;
    let timer: NodeJS.Timeout | undefined;
    const reveal = (async () => {
      try {
        await Promise.race([
          Promise.resolve(vscode.commands.executeCommand("wintestkit.properties.focus")),
          new Promise<void>((resolve) => { timer = setTimeout(resolve, 3000); }),
        ]);
        if (!this.disposed) await vscode.commands.executeCommand("wintestkit.spy.focus");
      } catch (error) {
        this.log.error(`Could not show the Properties view: ${String(error)}`);
      } finally {
        clearTimeout(timer);
        this.propertiesRevealing = undefined;
      }
    })();
    this.propertiesRevealing = reveal;
    await reveal;
  }
  private updateKeepalive(): void {
    clearInterval(this.keepaliveTimer);
    clearInterval(this.processTimer);
    this.keepaliveTimer = undefined;
    this.processTimer = undefined;
    if (!this.view?.visible && !this.propertiesView?.visible) this.cancelDetailsRetry(true);
    else if (this.detailsBusy || this.managedRetryNeeded || this.treeRetryNeeded) this.scheduleDetailsRetry();
    if (!this.disposed && (this.view?.visible || this.propertiesView?.visible)) this.processTimer = setInterval(() => this.checkRootProcesses(), 3000);
    if (!this.disposed && (this.view?.visible || this.propertiesView?.visible)) {
      this.keepaliveTimer = setInterval(() => void this.managedInspector?.keepalive(), 60_000);
    }
  }
  private postPropertiesVisibility(): void {
    this.post({ type: "propertiesVisibility", visible: !!this.propertiesView?.visible });
  }
  private currentProject(): Project | undefined {
    const uri = vscode.window.activeTextEditor?.document.uri;
    return (uri && this.projects.projectFor(uri)) || this.projects.all[0];
  }
  private postTour(): void {
    const focus = this.setup?.focus ?? { dim: false, spyLit: false };
    const tour = this.setup?.tour;
    const tutorial = tour?.phase === "extras" ? tour : undefined;
    this.post({
      type: "tour",
      dim: focus.dim,
      spyLit: focus.spyLit,
      tutorial:
        tutorial?.step === "spyPick" && !this.tutorialPrepared
          ? {
              ...tutorial,
              text:
                this.tutorialError ??
                tutorial.text +
                  " Preparing the objects preview before the next step…",
              buttons: [],
            }
          : tutorial,
    });
  }
  private tutorialActive(): boolean {
    return this.setup?.tour?.phase === "extras";
  }
  private syncTour(): void {
    const extras = this.setup?.tour?.phase === "extras";
    const opening = extras && !this.extrasActive;
    const closing = !extras && this.extrasActive;
    this.extrasActive = extras;
    if (opening || closing) {
      this.tutorialEpoch++;
      this.tutorialPrepared = false;
      this.tutorialSnapshot = [];
      this.tutorialError = undefined;
      this.tutorialPreparation = undefined;
      this.invalidateScope();
      this.pickRevision++;
      this.coverageRun++;
      clearTimeout(this.coverageTimer);
    }
    this.postTour();
    if (opening)
      void this.safe(async () => {
        await vscode.commands.executeCommand(
          "workbench.action.positionPanelBottom",
        );
        if (this.disposed || this.setup?.tour?.phase !== "extras") return;
        await vscode.commands.executeCommand("wintestkit.spy.focus");
        this.postTour();
        await this.ensureTutorial();
      });
    if (closing && this.view?.visible) void this.safe(() => this.refresh());
  }
  private post(message: SpyResponse, tutorial = false): void {
    if (this.tutorialActive() && !tutorial && message.type !== "tour") return;
    if (this.disposed) return;
    if (message.type === "roots" || message.type === "rootsDiff") this.rootNodes = message.nodes;
    if (message.type === "roots" || message.type === "selectionCleared" || message.type === "selectionPending") this.cancelDetailsRetry();
    if (message.type === "wpfDetails" && message.nodeId === this.selectedNodeId) {
      this.treeRetryNeeded = this.isBusy(message.blocked?.code);
      if (this.treeRetryNeeded) this.scheduleDetailsRetry();
    }
    if (message.type === "tour") {
      if (message.tutorial) { this.previewRevision++; this.currentPreview = undefined; }
      this.currentTour = message;
      if (this.propertiesReady) void this.propertiesView?.webview.postMessage(message);
    }
    if (message.type === "objectPreview") {
      if (message.nodeId !== this.selectedNodeId || tutorial) return;
      this.currentPreview = message;
      if (this.propertiesReady) void this.propertiesView?.webview.postMessage(message);
      return;
    }
    if (this.view) {
      this.trace.message("toWebview", message);
      void this.view.webview.postMessage(message);
    }
    if (message.type === "propertiesVisibility") return;
    if (message.type === "roots" || message.type === "selectionCleared") {
      this.selectedNodeId = undefined;
      this.previewRevision++;
      this.currentPreview = undefined;
      this.managedSnapshot = undefined;
      this.managedPanel?.select(undefined);
      this.propertiesHistory = this.propertiesHistory.filter((item) => item.type === "state");
    }
    const locatorTypes = ["suggestion", "suggestionLoading", "suggestionUnavailable"];
    if (message.type === "selectionPending" || message.type === "selected") {
      this.propertiesHistory = this.propertiesHistory.filter((item) => !["selected", "selectionPending", "pickedObjectGone", "allProperties", "propertiesLoading", "progress", "error", "definitions", ...locatorTypes].includes(item.type));
      if (message.type === "selectionPending") {
        void this.revealProperties();
        this.managedPanel?.select(message.nodeId);
        this.previewRevision++;
        this.currentPreview = undefined;
        this.managedSnapshot = undefined;
      }
    }
    if (message.type === "definitions" || message.type === "suggestion" || message.type === "suggestionLoading" || message.type === "suggestionUnavailable") {
      if (message.nodeId !== this.selectedNodeId) return;
      const replace = message.type === "definitions" ? ["definitions"] : locatorTypes;
      this.propertiesHistory = this.propertiesHistory.filter((item) => !replace.includes(item.type));
      this.propertiesHistory.push(message);
      if (this.propertiesReady) void this.propertiesView?.webview.postMessage(message);
      return;
    }
    // The Properties view keeps its own copy of the tree (labels, parents, paths), so every message that
    // changes the tree shape must reach it too; a diff it never saw leaves selected objects without a parent.
    if (["roots", "rootsDiff", "children", "childrenDiff", "wpfDetails", "state", "selected", "selectionCleared", "selectionPending", "pickedObjectGone", "allProperties", "propertiesLoading", "progress", "error"].includes(message.type)) {
      if (message.type === "state") this.propertiesHistory = this.propertiesHistory.filter((item) => item.type !== "state");
      if (message.type === "progress") this.propertiesHistory = this.propertiesHistory.filter((item) => item.type !== "progress" || item.taskId !== message.taskId);
      // Each of these carries the full state of its node, so a newer one supersedes the older ones.
      if (message.type === "children" && !message.append) this.propertiesHistory = this.propertiesHistory.filter((item) => (item.type !== "children" && item.type !== "childrenDiff") || item.nodeId !== message.nodeId);
      else if (message.type === "childrenDiff" || message.type === "wpfDetails") this.propertiesHistory = this.propertiesHistory.filter((item) => item.type !== message.type || item.nodeId !== message.nodeId);
      else if (message.type === "rootsDiff") this.propertiesHistory = this.propertiesHistory.filter((item) => item.type !== "rootsDiff");
      if (message.type !== "progress" || !message.done) this.propertiesHistory.push(message);
      if (this.propertiesHistory.length > PROPERTIES_HISTORY_LIMIT) {
        const drop = this.propertiesHistory.length - PROPERTIES_HISTORY_LIMIT;
        const tree = new Set(["children", "childrenDiff", "wpfDetails", "rootsDiff"]);
        let removed = 0;
        this.propertiesHistory = this.propertiesHistory.filter((item) => !(removed < drop && tree.has(item.type) && ++removed));
      }
      if (this.propertiesReady) void this.propertiesView?.webview.postMessage(message);
    }
  }
  private async restoreTutorial(): Promise<void> {
    this.postTour();
    if (this.tutorialPrepared) {
      for (const message of this.tutorialSnapshot) this.post(message, true);
      this.postTour();
    } else await this.ensureTutorial();
  }
  private ensureTutorial(): Promise<void> {
    if (
      !this.tutorialActive() ||
      this.tutorialPrepared ||
      this.tutorialError ||
      !this.view
    )
      return Promise.resolve();
    if (this.tutorialPreparation) return this.tutorialPreparation;
    const epoch = this.tutorialEpoch;
    this.postTour();
    const preparation = this.prepareTutorial(epoch)
      .catch((error: unknown) => {
        if (!this.tutorialCurrent(epoch)) return;
        const recovery =
          error instanceof RpcError &&
          (error.code === -32601 || error.code === -32602)
            ? "Install the Python wheel built with this extension; the installed backend does not support the tutorial's host-window lookup."
            : "Close the tutorial, focus this VS Code window, and reopen it.";
        this.tutorialError =
          "The VS Code example could not be prepared. " +
          String(error) +
          " " +
          recovery;
        this.log.error(this.tutorialError);
        this.postTour();
      })
      .finally(() => {
        if (this.tutorialPreparation === preparation)
          this.tutorialPreparation = undefined;
      });
    this.tutorialPreparation = preparation;
    return preparation;
  }
  private tutorialCurrent(epoch: number): boolean {
    return (
      !this.disposed && this.tutorialActive() && epoch === this.tutorialEpoch
    );
  }
  private async prepareTutorial(epoch: number): Promise<void> {
    await this.connecting?.promise.catch(() => undefined);
    if (!this.tutorialCurrent(epoch)) return;
    await this.stopPick();
    if (!this.tutorialCurrent(epoch)) return;
    const attempt = await this.connect();
    if (!this.tutorialCurrent(epoch)) return;
    const client = attempt.client;
    if (!client) throw new Error("Initialize a WinTestKit project first.");
    const hostRoots = await this.enumerate(client, "inspect.roots", {
      foregroundForProcessId: process.pid,
    });
    if (!this.tutorialCurrent(epoch)) return;
    const root = hostRoots.length === 1 ? hostRoots[0] : undefined;
    if (!root || root.info.controlType !== "Window")
      throw new Error("The hosting VS Code window was not found.");
    const children = await this.enumerate(client, "inspect.children", {
      nodeId: root.nodeId,
    });
    if (!this.tutorialCurrent(epoch)) return;
    const target = children[1];
    if (
      !target ||
      target.info.controlType !== "Pane" ||
      target.info.name !== root.info.name
    )
      throw new Error(
        "The hosting VS Code window does not expose its named content pane as its second child.",
      );
    const [desktopRoots, properties, suggestion, definitions] =
      await Promise.all([
        this.enumerate(client, "inspect.roots", { includeOtherApps: true }),
        client.request<InspectPropertiesResult>("inspect.properties", {
          nodeId: target.nodeId,
        }),
        client.request<Suggestion>("suggest.locator", {
          nodeId: target.nodeId,
        }),
        client.request<InspectDefinitionsResult>("inspect.definitions", {
          nodeId: target.nodeId,
        }),
      ]);
    if (!this.tutorialCurrent(epoch)) return;
    const roots = desktopRoots.some((node) => node.nodeId === root.nodeId)
      ? desktopRoots
      : [root, ...desktopRoots];
    if (this.client !== client)
      throw new Error("The automation server restarted during preparation.");
    const currentRoots = await this.enumerate(client, "inspect.roots", {
      foregroundForProcessId: process.pid,
    });
    if (!this.tutorialCurrent(epoch)) return;
    if (this.client !== client)
      throw new Error("The automation server restarted during preparation.");
    if (currentRoots.length !== 1 || currentRoots[0].nodeId !== root.nodeId)
      throw new Error(
        "The active VS Code window changed while preparing the example.",
      );
    this.suggestion = suggestion;
    this.definitionTargets = new Map(
      definitions.definitions.map((definition) => [definition.id, definition]),
    );
    const snapshot: SpyResponse[] = [
      {
        type: "state",
        picking: false,
        appRunning: true,
        targetName: root.info.name,
        hasProject: true,
        showOtherApps: true,
        bringToFront: this.bringToFront(),
      },
      { type: "roots", nodes: roots },
      {
        type: "children",
        nodeId: root.nodeId,
        nodes: children,
        expanded: true,
      },
      { type: "selected", nodeId: target.nodeId, properties, suggestion },
      {
        type: "definitions",
        nodeId: target.nodeId,
        state: "ready",
        ...definitions,
      },
    ];
    if (this.markersEnabled()) {
      const first = definitions.definitions[0];
      snapshot.push(
        {
          type: "coverage",
          nodeIds: [target.nodeId],
          covered: first
            ? {
                [target.nodeId]: {
                  count: definitions.definitions.length,
                  first: first.qualname,
                },
              }
            : {},
        },
      );
    }
    this.tutorialSnapshot = snapshot;
    for (const message of snapshot) this.post(message, true);
    this.tutorialPrepared = true;
    this.postTour();
    void readApplicationIcons(roots.map((node) => node.info.processId)).then((icons) => {
      if (!this.tutorialCurrent(epoch) || client !== this.client) return;
      const message: SpyResponse = { type: "rootIcons", icons };
      this.tutorialSnapshot.push(message);
      this.post(message, true);
      this.postTour();
    }).catch((error: unknown) => this.log.error(String(error)));
  }
  private state(): void {
    const project = this.currentProject();
    const treeWidth = this.treeWidth();
    this.post({
      type: "state",
      picking: this.picking,
      appRunning: this.appRunning,
      targetName: this.targetName ?? project?.name ?? "Test Target",
      appName: this.appName,
      appPids: this.appPids,
      hasProject: !!this.currentProject(),
      showOtherApps: this.showOtherApps,
      bringToFront: this.bringToFront(),
      basicProperties: this.basicProperties(),
      basicDefaults: [...DEFAULT_BASIC_PROPERTIES],
      ...(treeWidth === undefined ? {} : { treeWidth }),
      showRefreshCounts: vscode.workspace.getConfiguration("wintestkit.spy").get<boolean>("showRefreshCounts", false),
    });
    void vscode.commands.executeCommand(
      "setContext",
      "wintestkit.picking",
      this.picking,
    );
  }
  private async loading<T>(
    title: string,
    total: number,
    action: (
      phase: <Value>(
        label: string,
        work: () => Promise<Value>,
      ) => Promise<Value>,
    ) => Promise<T>,
    nodeId?: string,
    target: "tree" | "details" = "tree",
    delay = 0,
  ): Promise<T> {
    const taskId = ++this.taskId;
    let completed = 0;
    let finished = false;
    let failed = false;
    const active = new Set<string>();
    let visible = delay === 0;
    const timer = delay ? setTimeout(() => { visible = true; update(); }, delay) : undefined;
    const update = (done = false) => {
      if (!visible || (finished && !done)) return;
      this.post({
        type: "progress",
        taskId,
        title,
        phase: [...active].join(" · "),
        completed,
        total,
        done,
        nodeId,
        target,
        failed,
      });
    };
    update();
    try {
      return await action(async (label, work) => {
        active.add(label);
        update();
        try {
          const result = await work();
          completed++;
          return result;
        } finally {
          active.delete(label);
          update();
        }
      });
    } catch (error) {
      failed = true;
      if (isManagedNodeId(nodeId) && this.isStale(error) && !this.recovering && !this.pickedPoint) {
        await this.recoverStale();
        return undefined as T;
      }
      throw error;
    } finally {
      finished = true;
      if (timer) clearTimeout(timer);
      update(true);
    }
  }
  private async safe(action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (error) {
      this.log.error(String(error));
      if (error instanceof CompatibilityError && error.issue.kind === "older") {
        this.post({ type: "compatibilityBlocked", message: error.message, label: UPGRADE_LABEL });
      } else if (error instanceof RpcError && error.code === -32005) {
        // Reloading is the user's call: the tree may be what they were reading.
        this.post({
          type: "error",
          message: "The element is gone. Reload the objects view to refresh it.",
        });
      } else
        this.post({
          type: "error",
          message: error instanceof Error ? error.message : String(error),
        });
    }
  }
  private unbind(invalidatePick = true): void {
    this.cancelDetailsRetry();
    this.rootNodes = [];
    const client = this.client;
    const process = this.managedInspector?.sessionInfo?.process;
    if (process && this.project) this.disconnectedProcess = { project: this.project.root.toString(), process };
    if (client) { this.post({ type: "roots", nodes: [] }); this.selectedNodeId = undefined; this.managedSnapshot = undefined; }
    this.managedPanel?.dispose();
    this.managedPanel = undefined;
    this.managedInspector?.invalidate();
    this.managedInspector = undefined;
    this.notifications.forEach((subscription) => subscription.dispose());
    this.notifications = [];
    this.client = undefined;
    this.picking = false;
    this.suggestion = undefined;
    this.revision++;
    this.selection++;
    if (invalidatePick) this.pickRevision++;
    this.pickSession = undefined;
    this.loaded = false;
    if (client) void client.request("spy.stop").catch(() => {});
    this.state();
  }
  private async connect(): Promise<SpyConnection> {
    const project = this.currentProject();
    if (!project) {
      this.unbind();
      this.project = undefined;
      this.state();
      return { revision: this.revision };
    }
    if (
      this.client &&
      this.project?.root.toString() === project.root.toString()
    )
      return { client: this.client, revision: this.revision };
    const root = project.root.toString();
    if (
      this.connecting?.root === root &&
      this.connecting.scopeRevision === this.scopeRevision
    )
      return this.connecting.promise;
    const connecting = {
      root,
      scopeRevision: this.scopeRevision,
      promise: this.openConnection(project),
    };
    this.connecting = connecting;
    try {
      return await connecting.promise;
    } finally {
      if (this.connecting === connecting) this.connecting = undefined;
    }
  }
  private async openConnection(project: Project): Promise<SpyConnection> {
    this.unbind(false);
    this.project = project;
    const revision = this.revision;
    const connection = await this.servers.get(project);
    const client = connection.client;
    if (this.disposed || revision !== this.revision) return { revision };
    const appProcess = connection.initialized.config.app?.process;
    this.appName = appProcess
      ? path.win32.basename(appProcess).replace(/\.exe$/i, "")
      : undefined;
    this.client = client;
    this.managedInspector = new ManagedInspector(client, connection.initialized, (process) => void this.safe(() => this.recoverStale(process)), (line) => this.log.error(line), connection.hostCapability, (process) => void this.safe(() => this.recoverStale(process, true)), async (nodeId, call) => (await this.pickedCall(client, nodeId, call)).value);
    this.managedPanel = new ManagedPanel(this.managedInspector, (message) => {
      if (this.managedInspector?.visible && !this.tutorialActive()) {
        this.managedSnapshot = message;
        const snapshot = message as { failure?: { code?: string }; busyRead?: boolean };
        this.managedRetryNeeded = this.isBusy(snapshot.failure?.code) || !!snapshot.busyRead;
        if (this.managedRetryNeeded) this.scheduleDetailsRetry();
        if (this.propertiesReady) void this.propertiesView?.webview.postMessage(message);
      }
    });
    this.managedPanel.select(this.selectedNodeId);
    this.notifications = [
      client.onNotification("spy.hover", (value) => {
        if (!this.currentPick(client, value)) return;
        this.post({ type: "hover", ...(value as SpyHoverNotification) });
      }),
      client.onNotification("spy.cancelled", (value) => {
        if (!this.currentPick(client, value)) return;
        this.pickSession = undefined;
        this.pickRevision++;
        this.picking = false;
        this.state();
        this.managedPanel?.resumeAutoRead();
      }),
      client.onNotification("spy.picked", (value) => {
        void this.safe(async () => {
          if (!this.currentPick(client, value)) return;
          await this.revealPicked(client, value as SpyPickedNotification, true);
        });
      }),
    ];
    return { client, revision };
  }
  async refresh(): Promise<void> {
    if (this.tutorialActive()) return this.ensureTutorial();
    const nodeId = this.selectedNodeId;
    const selection = this.selection;
    // A refresh can invalidate server-side object handles even when the tree is
    // updated in place. Stop any pending invocation before starting the RPC.
    this.managedPanel?.select(undefined);
    const previewRevision = ++this.previewRevision;
    this.currentPreview = undefined;
    if (nodeId) this.post({ type: "objectPreview", nodeId, reason: "Refreshing preview\u2026" });
    const key = this.scopeRevision + ":" + this.currentProject()?.root.toString();
    // Each explicit refresh starts a new revision; late responses are ignored.
    this.refreshKey = key;
    const pending = this.refreshTree();
    this.refreshing = pending;
    try {
      await pending;
      if (this.refreshing === pending && nodeId && nodeId === this.selectedNodeId && selection === this.selection && this.client && this.loaded) this.managedPanel?.select(nodeId);
      if (nodeId && nodeId === this.selectedNodeId && selection === this.selection &&
          previewRevision === this.previewRevision && this.client) {
        void this.loadPreview(this.client, nodeId, selection);
      }
    } finally {
      if (this.refreshing === pending) this.refreshing = undefined;
    }
  }
  /**
   * Reloads only when nothing usable is on screen: nothing loaded yet, or the tree belongs to
   * another project. Events such as showing the panel or editing a config file must not reload a
   * tree the user is reading; reloading is the reload button's and the picker's job.
   */
  private refreshIfStale(): Promise<void> {
    const stale =
      !this.loaded ||
      this.currentProject()?.root.toString() !== this.project?.root.toString();
    return stale ? this.refresh() : Promise.resolve();
  }
  private async refreshTree(): Promise<void> {
    const scopeRevision = this.scopeRevision;
    const showOtherApps = this.showOtherApps;
    const restore = !this.skipRestore;
    const onlyIfListed = this.restoreIfListed;
    this.skipRestore = false;
    this.restoreIfListed = false;
    await this.loading("Loading objects", 2, async (phase) => {
      const attempt = await phase("Connecting to automation server", () =>
        this.connect(),
      );
      if (this.disposed || scopeRevision !== this.scopeRevision) return;
      if (!attempt.client) {
        if (attempt.revision !== this.revision) return;
        this.post({ type: "roots", nodes: [] });
        return;
      }
      const client = attempt.client;
      const disconnected = this.disconnectedProcess;
      const previousProcess = this.recoveryProcess ?? this.managedInspector?.sessionInfo?.process ??
        (disconnected && disconnected.project === this.project?.root.toString() ? disconnected.process : undefined);
      const revision = ++this.revision;
      let inPlace = this.loaded && !this.recovering;
      if (!inPlace) { this.selection++; this.suggestion = undefined; }
      const result = await phase("Refreshing root windows", () =>
        this.enumerateRefresh(client, showOtherApps),
      );
      if (this.disposed || !this.sameScope(scopeRevision, revision)) return;
      const { nodes, status } = result;
      this.appRunning = status.running;
      this.appPids = status.running ? status.pids : [];
      this.targetName = status.running ? status.mainWindowTitle : undefined;
      this.state();
      if (previousProcess) {
        const window = nodes.find((node) => node.info.processId === previousProcess.pid);
        let sameProcess = false;
        if (window) {
          try {
            const facts = await client.request<{ process: ManagedProcessIdentity }>("inspect.managed.identify", { nodeId: window.nodeId });
            sameProcess = facts.process.pid === previousProcess.pid && facts.process.creationTimeUtc === previousProcess.creationTimeUtc;
          } catch { sameProcess = status.pids.includes(previousProcess.pid); }
        }
        if (this.disposed || !this.sameScope(scopeRevision, revision)) return;
        if (!sameProcess) {
          this.managedInspector?.invalidate();
          this.selectedNodeId = undefined;
          inPlace = false;
          this.rememberSelection(undefined);
          this.expandedPaths = [];
        }
        this.disconnectedProcess = undefined;
      }
      if (inPlace) this.post({ type: "rootsDiff", nodes, revision, refresh: true });
      else this.post({ type: "roots", nodes });
      if (!inPlace) this.treeProcesses.clear();
      this.loaded = true;
      this.trackNodes(client, nodes, !inPlace);
      this.deferIcons(client, nodes, revision);
      if (restore && !inPlace && onlyIfListed && !this.selectionProcessListed(nodes)) {
        this.rememberSelection(undefined);
      } else if (restore && !inPlace) {
        if (this.recovering) {
          const loaded = new Map<string, NodeInfo[]>();
          await this.restoreExpanded(client, nodes, revision, loaded);
          await this.restoreSelection(client, nodes, revision, loaded);
        }
        else void this.restoreSelection(client, nodes, revision);
      }
    }, undefined, "tree", this.loaded ? 300 : 0);
  }
  // -- keeping the selection through a reload ------------------------------------------------
  private static readonly selectionKey = "wintestkit.spy.selection";
  private rememberSelection(path: PathSegment[] | undefined): void {
    const root = (this.project ?? this.currentProject())?.root.toString();
    this.selectionPath = path;
    this.selectionProject = path ? root : undefined;
    if (!this.memory || !root) return;
    const saved = { ...(this.memory.get<Record<string, unknown>>(SpyView.selectionKey) ?? {}) };
    if (path) saved[root] = path;
    else delete saved[root];
    void this.memory.update(SpyView.selectionKey, saved);
  }
  private recallSelection(): PathSegment[] | undefined {
    const root = (this.project ?? this.currentProject())?.root.toString();
    if (!root) return;
    if (this.selectionProject === root) return this.selectionPath;
    const saved = parseSelectionPath(this.memory?.get<Record<string, unknown>>(SpyView.selectionKey)?.[root]);
    this.selectionPath = saved;
    this.selectionProject = saved ? root : undefined;
    return saved;
  }
  /**
   * Selects the object that was selected before the reload or restart, by walking its route
   * through the fresh tree and opening each level on the way. If it is not there any more, says
   * so once in a VS Code notification and forgets it.
   */
  private async revealPicked(client: JsonRpcClient, picked: Omit<SpyPickedNotification, "suggestion"> & { suggestion?: Suggestion }, announce: boolean): Promise<void> {
          if (picked.blocked || picked.attachRequired) {
            await this.stopPick();
            const roots = await this.requestRoots(client);
            if (client !== this.client || this.disposed) return;
            const revision = ++this.revision;
            const wasLoaded = this.loaded;
            if (wasLoaded) this.post({ type: "rootsDiff", nodes: roots, revision });
            else { this.post({ type: "roots", nodes: roots }); this.loaded = true; }
            this.trackNodes(client, roots);
            this.deferIcons(client, roots, revision);
            const windowNode = roots.find((root) => root.nodeId === picked.node.nodeId || root.info.processId === picked.node.info.processId);
            if (windowNode && picked.blocked) {
              await this.managedInspector?.reportTreeFailure(windowNode.nodeId, picked.blocked);
              this.post({ type: "wpfDetails", nodeId: windowNode.nodeId, missing: false, blocked: picked.blocked });
              if (!wasLoaded) this.post({ type: "children", nodeId: windowNode.nodeId, nodes: [], expanded: true, blocked: picked.blocked });
            } else if (windowNode && picked.process) {
              this.treeProcesses.set(windowNode.nodeId, picked.process);
              if (await this.managedInspector?.attachTree(windowNode.nodeId, picked.process)) {
                if (client === this.client && revision === this.revision) {
                  this.post({ type: "error", message: "Inspector attached. Pick the element again to select its WPF node." });
                  await this.startPick();
                }
              } else if (client === this.client && revision === this.revision) {
                await this.showChildren(client, windowNode.nodeId, undefined, false);
              }
            }
            return;
          }
          this.pickedPoint = { ...picked.point, nodeId: picked.node.nodeId };
          this.selectedNodeId = picked.node.nodeId;
          const selection = ++this.selection;
          this.post({ type: "selectionPending", nodeId: picked.node.nodeId });
          void this.managedInspector?.select(picked.node.nodeId);
          let treeRevision = this.revision;
          const pickedScope = this.showOtherApps;
          const properties = await this.loading(
            "Inspecting picked object",
            2,
            async (phase) => {
              await phase("Stopping element picker", () => this.stopPick());
              this.trace.rpc("inspect.properties", picked.node.nodeId);
              return phase("Reading picked control properties", async () => {
                const read = (id: string) => client.request<InspectPropertiesResult>("inspect.properties", {
                  nodeId: id, includeAncestors: true, ...this.includeShown(),
                });
                return announce ? (await this.pickedCall(client, picked.node.nodeId, read)).value : read(picked.node.nodeId);
              });
            },
            picked.node.nodeId,
            "details",
          );
          if (!this.sameReveal(client, treeRevision, selection)) return;
          let pickedPath: PathSegment[] | undefined;
          let treePicked = picked.node;
          let revealNote: string | undefined;
          this.log.info(`Pick reveal: ${picked.node.info.controlType} '${picked.node.info.name}' (${picked.node.nodeId}), ${properties.ancestors.length} ancestors`);
          const revealed = await this.loading(
            "Revealing picked object",
            properties.ancestors.length + 2,
            async (phase) => {
              const roots = await phase("Reading root windows", () =>
                this.requestRoots(client, pickedScope),
              );
              if (!this.sameReveal(client, treeRevision, selection))
                return false;
              treeRevision = ++this.revision;
              const inPlace = this.loaded;
              if (inPlace) this.post({ type: "rootsDiff", nodes: roots, revision: treeRevision });
              else { this.post({ type: "roots", nodes: roots }); this.loaded = true; }
              this.trackNodes(client, roots, !inPlace);
              this.deferIcons(client, roots, treeRevision);
              const rootIndex = properties.ancestors.findIndex((ancestor) =>
                roots.some((root) => root.nodeId === ancestor.nodeId),
              );
              this.log.info(`Pick reveal: rootIndex ${rootIndex}`);
              const ancestors =
                rootIndex < 0 ? [] : properties.ancestors.slice(rootIndex);
              const processRoot = roots.find((root) => root.nodeId === (ancestors[0]?.nodeId ?? picked.node.nodeId));
              pickedPath = ancestors.length
                ? [...(processRoot ? [processSegment(processRoot.info)] : []), ...ancestors.map((ancestor) => segmentOf(ancestor.info)), segmentOf(picked.node.info)]
                : processRoot ? [processSegment(processRoot.info), segmentOf(picked.node.info)] : undefined;
              let current = processRoot;
              let reached = current ? 1 : 0;
              const total = ancestors.length + 1;
              if (!current) {
                revealNote = "Picked node was not found among the root windows.";
                this.log.error(`Pick reveal failed: ${revealNote}`);
              }
              const mixedWpfPath = isManagedSource(properties.source) || ancestors.some((ancestor) => isManagedSource(ancestor.source));
              for (const [index] of ancestors.entries()) {
                if (!current || !this.sameReveal(client, treeRevision, selection)) break;
                const wanted = ancestors[index + 1] ?? picked.node;
                let complete = true;
                const nodes = await phase("Loading " + (current.info.name || current.info.controlType), async () => {
                  if (!mixedWpfPath) return this.enumerate(client, "inspect.children", { nodeId: current!.nodeId });
                  const children: NodeInfo[] = [];
                  let token: string | undefined;
                  for (let page = 0; page < 20; page++) {
                    const result = await this.childrenPage(client, current!.nodeId, token);
                    if (Array.isArray(result)) { children.push(...result); token = undefined; break; }
                    if (!("nodes" in result)) { complete = false; break; }
                    children.push(...result.nodes);
                    token = result.nextPageToken;
                    if (!token) break;
                  }
                  if (token) complete = false;
                  return children;
                });
                if (!this.sameReveal(client, treeRevision, selection)) return false;
                if (inPlace) this.post({ type: "childrenDiff", nodeId: current.nodeId, nodes, revision: treeRevision });
                else this.post({ type: "children", nodeId: current.nodeId, nodes });
                this.trackNodes(client, nodes);
                const byId = nodes.find((node) => node.nodeId === wanted.nodeId);
                const identityMatch = !byId && isManagedSource(wanted.source) ? matchManagedIdentity(wanted, nodes) : undefined;
                const match = byId ?? (isManagedSource(wanted.source) ? identityMatch?.node : bestMatch(segmentOf(wanted.info), nodes));
                this.log.info(`Pick reveal level ${index + 1}: wanted ${wanted.info.controlType} '${wanted.info.name}' (${wanted.nodeId}), page had ${nodes.length} children [${nodes.map((node) => node.info.controlType).join(", ")}], found ${match ? "yes" : "no"}, matched by ${byId ? "id" : match ? `identity: ${identityMatch?.attributes.join("+") ?? "type"}` : "none"}`);
                if (!match || !complete) {
                  revealNote = `Revealed ${reached} of ${total} levels; the rest of the tree changed while loading.`;
                  this.log.error(`Pick reveal failed: ${revealNote} ${complete ? "Target missing." : "Tree page incomplete."}`);
                  break;
                }
                current = match;
                reached++;
                const pathIndex = (processRoot ? 1 : 0) + index + 1;
                if (pickedPath) pickedPath[pathIndex] = segmentOf(match.info, nodes.indexOf(match));
              }
              if (current) treePicked = current;
              if (!ancestors.length && processRoot?.nodeId !== picked.node.nodeId) {
                revealNote = `Revealed ${reached} of ${total} levels; the rest of the tree changed while loading.`;
                this.log.error(`Pick reveal failed: ${revealNote} No ancestor path.`);
              }
              return true;
            },
            picked.node.nodeId,
          );
          if (!revealed || !this.sameReveal(client, treeRevision, selection))
            return;
          this.suggestion = picked.suggestion;
          this.selectedNodeId = picked.node.nodeId;
          this.managedPanel?.select(picked.node.nodeId, isManagedSource(properties.source));
          if (pickedPath) this.rememberSelection(pickedPath);
          this.post({
            type: "picked",
            node: treePicked,
            suggestion: picked.suggestion,
            ancestors: properties.ancestors,
          });
          this.post({
            type: "selected",
            nodeId: picked.node.nodeId,
            properties,
            suggestion: picked.suggestion,
            treeNodeId: treePicked.nodeId,
            revealNote: [revealNote, picked.innerElement && `Picked ${picked.innerElement.type}${picked.innerElement.text ? ` '${picked.innerElement.text}'` : ""} inside this ${picked.node.info.controlType}.`].filter(Boolean).join(" ") || undefined,
          });
          if (!announce) return;
          this.loadSelectionDetails(client, picked.node.nodeId, selection);
          const choice = await vscode.window.showInformationMessage(
            "Picked " +
              picked.node.info.controlType +
              ' "' +
              picked.node.info.name +
              '"',
            "Open Spy",
          );
          if (choice)
            await vscode.commands.executeCommand("wintestkit.spy.focus");
  }
  private async pickedCall<T>(client: JsonRpcClient, nodeId: string, call: (id: string) => Promise<T>): Promise<{ value: T; nodeId: string }> {
    try { return { value: await call(nodeId), nodeId }; }
    catch (error) {
      const code = (error as { code?: number; data?: { code?: string } })?.data?.code;
      const point = this.pickedPoint;
      if (!point || point.nodeId !== nodeId || client !== this.client ||
        !((error as { code?: number })?.code === -32005 || code === "objectStale" || code === "mappingFailed")) throw error;
      let replacementId: string | undefined;
      try {
        const picked = await client.request<SpyPickedNotification>("spy.repick", { x: point.x, y: point.y, tree: "visual" });
        if (this.pickedPoint !== point || client !== this.client) throw new Error("Selection changed during re-pick.");
        if (picked.blocked || picked.attachRequired || !picked.node) throw new Error("Could not re-resolve the picked object.");
        replacementId = picked.node.nodeId;
        await this.revealPicked(client, picked, false);
        if (this.selectedNodeId !== picked.node.nodeId || this.pickedPoint?.nodeId !== picked.node.nodeId) throw new Error("Could not reveal the picked object.");
        const value = await call(picked.node.nodeId);
        this.loadSelectionDetails(client, picked.node.nodeId, this.selection);
        this.log.info(`Picked object was replaced by the app; re-resolved at (${point.x}, ${point.y}).`);
        return { value, nodeId: picked.node.nodeId };
      } catch (failure) {
        this.log.error("Re-pick failed: " + String(failure));
        if (this.pickedPoint && (this.pickedPoint === point || (replacementId && this.pickedPoint.nodeId === replacementId && this.selectedNodeId === replacementId))) this.post({ type: "pickedObjectGone", nodeId: this.selectedNodeId ?? nodeId });
        throw failure;
      }
    }
  }
  private selectionProcessListed(roots: NodeInfo[]): boolean {
    const first = this.recallSelection()?.[0];
    if (!first) return false;
    if (first.controlType !== "Process") return true;
    return roots.some((root) => processSegment(root.info).automationId === first.automationId);
  }
  private async restoreSelection(client: JsonRpcClient, roots: NodeInfo[], revision: number, loaded?: Map<string, NodeInfo[]>): Promise<void> {
    const path = this.recallSelection();
    if (!path?.length) return;
    const selection = this.selection;
    const stale = () =>
      this.disposed || this.client !== client || revision !== this.revision ||
      selection !== this.selection || this.tutorialActive();
    try {
      let candidates = roots;
      let current: NodeInfo | undefined;
      let start = 0;
      if (path[0].controlType === "Process") {
        candidates = roots.filter((root) => processSegment(root.info).automationId === path[0].automationId);
        start = 1;
      }
      for (let depth = start; depth < path.length; depth++) {
        if (current) {
          const cached = loaded?.get(current.nodeId);
          if (this.recovering && this.recoveryFailures.has(current.nodeId)) return;
          candidates = cached ?? await this.enumerate(client, "inspect.children", { nodeId: current.nodeId });
          if (stale()) return;
          if (!cached) {
            this.post({ type: "children", nodeId: current.nodeId, nodes: candidates, expanded: true });
            this.trackNodes(client, candidates);
          }
        }
        const segment = path[depth];
        const indexed = segment.index === undefined ? undefined : candidates[segment.index];
        const match = this.recovering && depth > start
          ? (indexed?.info.controlType === segment.controlType ? indexed : undefined)
          : bestMatch(segment, candidates);
        if (this.recovering && depth === start && match && path[start].processId !== undefined && match.info.processId !== path[start].processId) {
          this.rememberSelection(undefined);
          return;
        }
        if (!match) {
          if (this.recovering && current) {
            this.rememberSelection(path.slice(0, depth));
            await this.handle({ type: "select", nodeId: current.nodeId });
            this.post({ type: "selectionRestored", nodeId: current.nodeId });
            void vscode.window.showWarningMessage("The selected object no longer exists. Spy selected its closest surviving ancestor.");
          } else this.selectionNotFound(path);
          return;
        }
        current = match;
      }
      if (!current || stale()) return;
      const previousPick = this.pickedPoint;
      if (previousPick) this.pickedPoint = { ...previousPick, nodeId: current.nodeId };
      await this.handle({ type: "select", nodeId: current.nodeId }, !!previousPick);
      this.post({ type: "selectionRestored", nodeId: current.nodeId });
    } catch (error) {
      if (!stale()) {
        this.log.error("Could not restore the selection: " + String(error));
        if (this.recovering) this.post({ type: "error", message: "Could not restore the selected object. Refresh Spy or use Retry." });
      }
    }
  }
  private async restoreExpanded(client: JsonRpcClient, roots: NodeInfo[], revision: number, loaded: Map<string, NodeInfo[]>): Promise<void> {
    const paths = this.expandedPaths.slice(0, 200).sort((a, b) => a.length - b.length);
    let count = 0;
    for (const path of paths) {
      let candidates = roots;
      let start = 0;
      if (path[0].controlType === "Process") {
        candidates = roots.filter((root) => processSegment(root.info).automationId === path[0].automationId);
        start = 1;
      }
      for (let depth = start; depth < path.length && depth < 64; depth++) {
        if (this.disposed || client !== this.client || revision !== this.revision || count >= 200) return;
        const segment = path[depth];
        const current = depth === start ? bestMatch(segment, candidates) :
          (segment.index === undefined ? undefined : candidates[segment.index]);
        if (!current || (depth === start && segment.processId !== undefined && current.info.processId !== segment.processId) ||
          (depth > start && current.info.controlType !== segment.controlType) || !current.hasChildren) break;
        let children = loaded.get(current.nodeId);
        if (!children) {
          try { children = await this.enumerate(client, "inspect.children", { nodeId: current.nodeId }); }
          catch { this.recoveryFailures.add(current.nodeId); break; }
          if (this.disposed || client !== this.client || revision !== this.revision) return;
          loaded.set(current.nodeId, children); count++;
          this.post({ type: "children", nodeId: current.nodeId, nodes: children, expanded: true });
          this.trackNodes(client, children);
        }
        candidates = children;
      }
    }
  }
  private selectionNotFound(path: PathSegment[]): void {
    const target = path[path.length - 1];
    this.rememberSelection(undefined);
    void vscode.window.showWarningMessage(
      "Spy could not find " + describeSegment(target) + " again after reloading, so nothing is " +
        "selected. It may have changed or closed.",
    );
  }
  /** Resolve a diagnostic path against a fresh, bounded UIA snapshot before revealing it. */
  private async revealRelocation(path: string): Promise<void> {
    if (this.tutorialActive()) return;
    const parts = path
      .split(" › ")
      .map((part) => part.trim())
      .filter(Boolean);
    if (!parts.length || parts.length > 12)
      throw new Error("Invalid relocation path.");
    const connection = await this.connect();
    if (!connection.client) throw new Error("No active WinTestKit project.");
    const client = connection.client;
    const status = await client.request<AppStatusResult>("app.status");
    if (!status.running)
      throw new Error(
        "Start the target app before revealing a relocated element.",
      );
    const roots = await this.requestRoots(client, false);
    const matches: { node: NodeInfo; ancestors: NodeInfo[] }[] = [];
    let visited = 0;
    let exhausted = false;
    const deadline = Date.now() + 2500;
    const short = (node: NodeInfo) => {
      const info = node.info;
      const labels = [info.controlType];
      if (info.automationId) labels.push("#" + info.automationId);
      if (info.name) labels.push('"' + info.name + '"');
      if (!info.automationId && !info.name && info.className)
        labels.push("[" + info.className + "]");
      return labels.join(" ");
    };
    const walk = async (
      node: NodeInfo,
      ancestors: NodeInfo[],
      depth: number,
    ) => {
      if (matches.length > 1) return;
      if (Date.now() > deadline || ++visited > 1000) {
        exhausted = true;
        return;
      }
      if (depth > 12) return;
      const chain = [...ancestors, node];
      const pathStart = chain.length - parts.length;
      const includesWindow = parts[0].startsWith("Window ");
      const pathMatches = includesWindow
        ? chain.length === parts.length &&
          chain.every((item, index) => short(item) === parts[index])
        : pathStart >= 0 &&
          chain
            .slice(pathStart)
            .every((item, index) => short(item) === parts[index]);
      if (pathMatches) matches.push({ node, ancestors });
      if (depth >= parts.length || !node.hasChildren) return;
      const children = await this.enumerate(client, "inspect.children", {
        nodeId: node.nodeId,
      });
      for (const child of children) await walk(child, chain, depth + 1);
    };
    for (const root of roots) await walk(root, [], 1);
    if (exhausted)
      throw new Error(
        "Relocation search exceeded its safety limit; narrow the desktop scope and try again.",
      );
    if (matches.length !== 1)
      throw new Error(
        matches.length
          ? "Relocation path is ambiguous in the current UI."
          : "Relocation path is no longer present; refresh Spy.",
      );
    const target = matches[0];
    const revision = ++this.revision;
    this.selection++;
    this.post({ type: "roots", nodes: roots });
    this.trackNodes(client, roots, true);
    for (const ancestor of target.ancestors) {
      const children = await this.enumerate(client, "inspect.children", {
        nodeId: ancestor.nodeId,
      });
      if (revision !== this.revision || client !== this.client) return;
      this.post({ type: "children", nodeId: ancestor.nodeId, nodes: children });
      this.trackNodes(client, children);
    }
    await this.handle({ type: "select", nodeId: target.node.nodeId });
    await vscode.commands.executeCommand("wintestkit.spy.focus");
  }
  private sameScope(scopeRevision: number, revision: number): boolean {
    return scopeRevision === this.scopeRevision && revision === this.revision;
  }
  private sameReveal(
    client: JsonRpcClient,
    treeRevision: number,
    selection: number,
  ): boolean {
    return (
      this.client === client &&
      treeRevision === this.revision &&
      selection === this.selection
    );
  }
  private invalidateScope(): void {
    this.loaded = false;
    this.scopeRevision++;
    this.revision++;
    this.selection++;
    this.suggestion = undefined;
  }
  private requestRoots(
    client: JsonRpcClient,
    showOtherApps = this.showOtherApps,
  ): Promise<NodeInfo[]> {
    this.trace.rpc("inspect.roots");
    return this.enumerate(client, "inspect.roots", showOtherApps ? { includeOtherApps: true } : undefined);
  }
  async refreshForProject(project: Project): Promise<void> {
    if (
      this.view?.visible &&
      this.currentProject()?.root.toString() === project.root.toString()
    )
      await this.safe(() => this.refresh());
  }
  private async startPick(): Promise<void> {
    if (this.tutorialActive()) return;
    this.pickedPoint = undefined;
    // The picker comes first: the automatic Properties read stops sending batches until the pick ends.
    this.managedPanel?.pauseAutoRead();
    const token = ++this.pickRevision;
    const view = this.view;
    await this.loading("Starting picker", 2, async (phase) => {
      const attempt = await phase("Connecting to automation server", () =>
        this.connect(),
      );
      if (!attempt.client || token !== this.pickRevision || this.disposed || this.view !== view || !view?.visible || this.tutorialActive() || this.client !== attempt.client) return;
      const client = attempt.client;
      const sessionId = randomBytes(16).toString("hex");
      this.pickSession = sessionId;
      this.trace.rpc("spy.start");
      await phase("Starting element picker", () => client.request("spy.start", {
        sessionId,
        tree: "visual",
        foregroundForProcessId: process.pid,
      }));
      if (
        token !== this.pickRevision ||
        this.client !== client ||
        this.disposed || !this.view?.visible || this.tutorialActive() || this.pickSession !== sessionId
      )
        return;
      this.picking = true;
      this.state();
    });
  }
  private async stopPick(): Promise<void> {
    this.pickRevision++;
    this.pickSession = undefined;
    this.picking = false;
    this.state();
    if (this.client) {
      this.trace.rpc("spy.stop");
      await this.client.request("spy.stop");
    }
  }
  private currentPick(client: JsonRpcClient, value: unknown): boolean {
    return !this.disposed && !this.tutorialActive() &&
      !!this.view?.visible && this.client === client && !!this.pickSession &&
      !!value && typeof value === "object" &&
      (value as { sessionId?: unknown }).sessionId === this.pickSession;
  }
  // Icons belong to the tree, not to what is selected in it: choosing a row (or restoring the
  // previous selection) while they load must not discard them, so only the tree revision counts.
  private deferIcons(client: JsonRpcClient, nodes: NodeInfo[], revision: number): void {
    void readApplicationIcons(nodes.map((node) => node.info.processId)).then((icons) => {
      if (!this.disposed && this.client === client && revision === this.revision)
        this.post({ type: "rootIcons", icons });
    }).catch((error: unknown) => this.log.error(String(error)));
  }
  private partialNodes(error: unknown, nodeId?: string, current = true): NodeInfo[] | undefined {
    if (!(error instanceof RpcError) || error.code !== -32005 || !error.data || typeof error.data !== "object") return;
    const data = error.data as { nodes?: NodeInfo[]; complete?: unknown; errors?: { index: number; message: string }[] };
    if (data.complete !== false || !Array.isArray(data.nodes) || !Array.isArray(data.errors) ||
      !data.nodes.every((node) => node && typeof node.nodeId === "string" && !!node.info)) return;
    if (current) this.post({ type: "enumerationIncomplete", nodeId, message: "Incomplete object enumeration. " +
      data.errors.map((entry) => String(entry.index) + ": " + String(entry.message)).join("; ") });
    return data.nodes;
  }
  /** `keepSession`: the inspector has just attached again, so only the tree and its selected handle are replaced. */
  private async recoverStale(process?: ManagedProcessIdentity, keepSession = false): Promise<void> {
    if (this.recovering || this.disposed || !this.client) return;
    this.recovering = true;
    this.recoveryFailures.clear();
    this.recoveryProcess = process ?? this.managedInspector?.sessionInfo?.process;
    if (!keepSession) this.managedInspector?.invalidate();
    const selected = this.selectedNodeId;
    try { await this.refresh(); }
    catch (error) {
      const reason = "Inspector recovery failed. Refresh Spy or use Retry: " + (error instanceof Error ? error.message : String(error));
      if (selected) this.post({ type: "objectPreview", nodeId: selected, reason });
      this.post({ type: "roots", nodes: [] });
      this.post({ type: "error", message: reason });
    } finally { this.recovering = false; this.recoveryProcess = undefined; }
  }
  private isStale(error: unknown): boolean {
    const code = (error as { data?: { code?: string } })?.data?.code;
    return code === "sessionStale" || code === "processExited" || code === "processReused" ||
      (error instanceof RpcError && error.code === -32005);
  }
  private async childrenPage(client: JsonRpcClient, nodeId: string, pageToken?: string, autoAttach = true, allowFallback = true): Promise<InspectChildrenResult> {
    const result = await this.pickedCall(client, nodeId, (id) => this.childrenPageRaw(client, id, id === nodeId ? pageToken : undefined, autoAttach, allowFallback));
    return result.value;
  }
  private async childrenPageRaw(client: JsonRpcClient, nodeId: string, pageToken?: string, autoAttach = true, allowFallback = true): Promise<InspectChildrenResult> {
    const params = { nodeId, tree: "visual" as const, ...(pageToken ? { pageToken } : {}) };
    this.trace.rpc("inspect.children", nodeId);
    let result = await client.request<InspectChildrenResult>("inspect.children", params);
    if (!Array.isArray(result) && "attachRequired" in result) {
      this.treeProcesses.set(nodeId, result.process);
      if (this.recovering && this.recoveryProcess?.pid === result.process.pid &&
        this.recoveryProcess.creationTimeUtc !== result.process.creationTimeUtc) {
        this.rememberSelection(undefined);
        this.recoveryFailures.add(nodeId);
        return [];
      }
      if (autoAttach && this.managedInspector) {
        const key = `${result.process.pid}:${result.process.creationTimeUtc}`;
        const last = this.recoveryAttempts.get(key);
        if (this.recovering && last !== undefined && Date.now() - last < 30_000) {
          return { blocked: { code: "reattachLimited", hint: "Automatic reattach was attempted recently. Use Retry to try again." } };
        }
        if (this.recovering) this.recoveryAttempts.set(key, Date.now());
        const attached = await this.managedInspector.attachTree(nodeId, result.process);
        if (!attached && this.managedInspector.treeFailure) {
          this.post({ type: "wpfDetails", nodeId, missing: false, blocked: this.managedInspector.treeFailure });
          return { blocked: this.managedInspector.treeFailure };
        }
        this.trace.rpc("inspect.children", nodeId);
        result = await client.request<InspectChildrenResult>("inspect.children", params);
        if (!Array.isArray(result) && "attachRequired" in result && this.managedInspector.treeFailure) {
          result = { blocked: this.managedInspector.treeFailure };
        }
      }
      if (!Array.isArray(result) && "attachRequired" in result) {
        if (!allowFallback) return result;
        this.trace.rpc("inspect.children", nodeId);
        const fallback = await client.request<InspectChildrenResult>("inspect.children", { nodeId });
        this.post({ type: "wpfDetails", nodeId, missing: true });
        return fallback;
      }
    }
    if (!Array.isArray(result) && "blocked" in result) await this.managedInspector?.reportTreeFailure(nodeId, result.blocked);
    this.post({ type: "wpfDetails", nodeId, missing: false, ...(!Array.isArray(result) && "blocked" in result ? { blocked: result.blocked } : {}) });
    return result;
  }
  private async showChildren(client: JsonRpcClient, nodeId: string, pageToken?: string, autoAttach = true, expanded = false, diff = false): Promise<void> {
    let revision = this.revision;
    let result: InspectChildrenResult;
    try {
      const picked = this.pickedPoint?.nodeId === nodeId;
      result = await this.childrenPage(client, nodeId, pageToken, autoAttach, !diff);
      if (picked && this.pickedPoint && this.pickedPoint.nodeId !== nodeId) {
        nodeId = this.pickedPoint.nodeId;
        revision = this.revision;
      }
      if (diff && !Array.isArray(result) && "nodes" in result) {
        const collected = [...result.nodes];
        let token = result.nextPageToken;
        const seen = new Set<string>();
        while (token && !seen.has(token) && seen.size < 200) {
          seen.add(token);
          const page = await this.childrenPage(client, nodeId, token, autoAttach, !diff);
          if (client !== this.client || revision !== this.revision) return;
          if (Array.isArray(page)) { collected.push(...page); token = undefined; }
          else if ("nodes" in page) { collected.push(...page.nodes); token = page.nextPageToken; }
          else { result = page; break; }
        }
        if (Array.isArray(result) || "nodes" in result) result = { nodes: collected, nextPageToken: token };
      }
    } catch (error) {
      if (client !== this.client || revision !== this.revision) return;
      const code = (error as { data?: { code?: string } })?.data?.code;
      if (code === "objectStale" && isManagedNodeId(nodeId) && !this.recovering) {
        await this.recoverStale(undefined, true); return;
      }
      if (this.isStale(error) && isManagedNodeId(nodeId) && !this.recovering) { await this.recoverStale(); return; }
      const hint = error instanceof RpcError && error.code === -32005
        ? "The element is gone. Reload the objects view to refresh it."
        : error instanceof Error ? error.message : String(error);
      if (error instanceof RpcError && error.code === -32005) this.post({ type: "error", message: hint });
      result = { blocked: { code: "childrenUnavailable", hint } };
      this.post({ type: "wpfDetails", nodeId, missing: false, blocked: result.blocked });
    }
    if (client !== this.client || revision !== this.revision) return;
    const nodes = Array.isArray(result) ? result : "nodes" in result ? result.nodes : [];
    const nextPageToken = !Array.isArray(result) && "nodes" in result ? result.nextPageToken : undefined;
    if (nextPageToken) this.treeTokens.set(nodeId, nextPageToken); else this.treeTokens.delete(nodeId);
    const blocked = !Array.isArray(result) && "blocked" in result ? result.blocked :
      diff && (!nodes.length || nextPageToken || (!Array.isArray(result) && "attachRequired" in result))
        ? { code: "childrenIncomplete", hint: "Refresh did not return a complete child list." } : undefined;
    if (diff) this.post({ type: "childrenDiff", nodeId, nodes, revision, nextPageToken, blocked });
    else this.post({ type: "children", nodeId, nodes, append: !!pageToken, nextPageToken, ...(expanded ? { expanded: true } : {}), blocked });
    this.trackNodes(client, nodes);
  }
  private async enumerate(client: JsonRpcClient, method: string, params?: { nodeId?: string; includeOtherApps?: boolean; foregroundForProcessId?: number }): Promise<NodeInfo[]> {
    const revision = this.revision;
    try {
      if (method !== "inspect.children" || !params?.nodeId) return await (params ? client.request<NodeInfo[]>(method, params) : client.request<NodeInfo[]>(method));
      const nodes: NodeInfo[] = [];
      let token: string | undefined;
      const seen = new Set<string>();
      do {
        if (token) {
          if (seen.has(token) || seen.size >= 200) throw new Error("Child enumeration limit reached.");
          seen.add(token);
        }
        const result = await this.childrenPage(client, params.nodeId, token);
        if (Array.isArray(result)) return [...nodes, ...result];
        if (!("nodes" in result)) {
          this.post({ type: "children", nodeId: params.nodeId, nodes: [], expanded: true, blocked: "blocked" in result ? result.blocked : undefined });
          throw new Error("WPF tree is not available");
        }
        nodes.push(...result.nodes);
        token = result.nextPageToken;
      } while (token);
      return nodes;
    } catch (error) {
      const nodes = this.partialNodes(error, params?.nodeId, !this.disposed && client === this.client && revision === this.revision);
      if (nodes) return nodes;
      throw error;
    }
  }
  private async enumerateRefresh(client: JsonRpcClient, showOtherApps: boolean): Promise<InspectRefreshResult> {
    const revision = this.revision;
    try {
      return await (showOtherApps
        ? client.request<InspectRefreshResult>("inspect.refresh", { includeOtherApps: true })
        : client.request<InspectRefreshResult>("inspect.refresh"));
    } catch (error) {
      const nodes = this.partialNodes(error, undefined, !this.disposed && client === this.client && revision === this.revision);
      if (!nodes) throw error;
      const status = await client.request<AppStatusResult>("app.status").catch((): AppStatusResult => ({
        running: this.appRunning, owned: false, pids: [], mainWindowTitle: this.targetName,
      }));
      return { nodes, status };
    }
  }
  /**
   * Generates the suggested locator for the selected object. It searches the whole window once per
   * candidate, which can take 20 seconds or more in a large application and keeps the automation
   * server busy meanwhile, so it only runs when the user asks.
   */
  private async generateLocator(nodeId: string): Promise<void> {
    const client = this.client;
    if (!client || nodeId !== this.selectedNodeId || this.tutorialActive()) return;
    const selection = this.selection;
    if (this.suggestion?.unique) {
      this.post({ type: "suggestion", nodeId, suggestion: this.suggestion });
      return;
    }
    if (this.generatingLocatorFor === selection) return;
    this.generatingLocatorFor = selection;
    const current = () =>
      !this.disposed && !this.tutorialActive() &&
      client === this.client && selection === this.selection && nodeId === this.selectedNodeId;
    this.post({ type: "suggestionLoading", nodeId });
    try {
      const retried = await this.pickedCall(client, nodeId, (id) => client.request<Suggestion>("suggest.locator", { nodeId: id }));
      nodeId = retried.nodeId;
      const suggestion = retried.value;
      if (client !== this.client || nodeId !== this.selectedNodeId) return;
      this.suggestion = suggestion;
      this.post({ type: "suggestion", nodeId, suggestion });
    } catch (error) {
      if (!current()) return;
      if (!(error instanceof RpcError && error.code === -32006)) this.log.error(String(error));
      this.post({ type: "suggestionUnavailable", nodeId, reason: error instanceof Error ? error.message : String(error) });
    } finally {
      if (this.generatingLocatorFor === selection) this.generatingLocatorFor = undefined;
    }
  }
  private async handle(message: SpyRequest, restoringPick = false): Promise<void> {
    if (message.type === "upgradePackage") {
      const project = this.currentProject();
      if (project) {
        await vscode.commands.executeCommand("wintestkit.installCompatiblePackage", project.root);
        await vscode.commands.executeCommand("wintestkit.spy.focus");
        await this.refresh();
      }
      return;
    }
    if (message.type === "expandedPaths") { this.expandedPaths = message.paths; return; }
    if (message.type === "showProperties") {
      if (this.propertiesView) this.propertiesView.show?.(true);
      else await vscode.commands.executeCommand("wintestkit.properties.focus");
      return;
    }
    if (message.type === "propertiesReady") return;
    if (message.type.startsWith("managed")) { await this.managedPanel?.handle(message as import("./messages").ManagedRequest); return; }
    if (message.type === "tour") {
      const setup = this.setup;
      if (setup?.tour?.phase !== "extras") return;
      switch (message.action) {
        case "back":
          setup.back();
          if (setup.tour?.phase !== "extras")
            await vscode.commands.executeCommand("wintestkit.sidebar.focus");
          return;
        case "next":
          return setup.tour.step !== "spyPick" || this.tutorialPrepared
            ? setup.next()
            : undefined;
        case "close":
          return setup.close();
        case "skip":
          return setup.skip();
        case "finish":
          return setup.finish();
        case "disable":
          return void (await vscode.commands.executeCommand(
            "wintestkit.disable",
          ));
      }
    }
    if (this.tutorialActive()) {
      if (message.type === "ready") await this.restoreTutorial();
      return;
    }
    if (message.type === "chooseApp") {
      await vscode.commands.executeCommand("wintestkit.chooseApp");
      return;
    }
    if (message.type === "ready") {
      this.postPropertiesVisibility();
      this.postTour();
      if (typeof message.showOtherApps === "boolean")
        this.showOtherApps = message.showOtherApps;
      this.invalidateScope();
      return this.refresh();
    }
    if (message.type === "selectionRemoved") {
      this.cancelDetailsRetry();
      this.pickedPoint = undefined;
      this.selectedNodeId = undefined;
      this.selection++;
      this.rememberSelection(undefined);
      this.post({ type: "selectionCleared" });
      return;
    }
    if (message.type === "refreshCounts") {
      this.log.debug("Spy refresh: " + JSON.stringify(message));
      return;
    }
    if (message.type === "refreshChildren") {
      const client = this.client;
      if (!client || message.revision !== this.revision) return;
      await this.showChildren(client, message.nodeId, undefined, true, false, true);
      return;
    }
    if (message.type === "treeAttach" || message.type === "treeMore") {
      const client = this.client;
      if (!client) return;
      if (message.type === "treeAttach") {
        const process = this.treeProcesses.get(message.nodeId);
        if (process) {
          const attached = await this.managedInspector?.attachTree(message.nodeId, process);
          const failure = this.managedInspector?.treeFailure;
          if (!attached && failure) {
            this.post({ type: "wpfDetails", nodeId: message.nodeId, missing: false, blocked: failure });
            this.post({ type: "children", nodeId: message.nodeId, nodes: [], expanded: true, blocked: failure });
          } else {
            await this.showChildren(client, message.nodeId, undefined, false, true);
          }
        }
      } else if (this.treeTokens.get(message.nodeId) === message.pageToken) {
        await this.showChildren(client, message.nodeId, message.pageToken);
      }
      return;
    }
    if (message.type === "bringToFront") {
      await vscode.workspace
        .getConfiguration("wintestkit.spy")
        .update(
          "bringWindowToFront",
          message.enabled,
          vscode.ConfigurationTarget.Global,
        );
      return this.state();
    }
    if (message.type === "showOtherApps") {
      if (this.showOtherApps === message.enabled) return;
      this.showOtherApps = message.enabled;
      const keep = !!this.selectedNodeId && !!this.recallSelection()?.length;
      this.skipRestore = !keep;
      this.restoreIfListed = keep;
      this.invalidateScope();
      return this.refresh();
    }
    if (message.type === "refresh") return this.refresh();
    if (message.type === "pick") return this.startPick();
    if (message.type === "stopPick") { await this.stopPick(); this.managedPanel?.resumeAutoRead(); return; }
    if (message.type === "basicProperty") {
      await this.setBasicProperty(message.key, message.pinned);
      return;
    }
    if (message.type === "resetBasicProperties") {
      await this.resetBasicProperties();
      return;
    }
    if (message.type === "treeWidth") {
      this.rememberTreeWidth(message.width);
      return;
    }
    if (message.type === "generateLocator") {
      await this.generateLocator(message.nodeId);
      return;
    }
    if (message.type === "retryPreview") {
      if (this.client && this.selectedNodeId) {
        const nodeId = this.selectedNodeId;
        this.post({ type: "objectPreview", nodeId, reason: "Capturing preview\u2026" });
        void this.loadPreview(this.client, nodeId, this.selection);
      }
      return;
    }
    if (message.type === "openPreview") {
      await this.previewViewer.show(message.view, message.dataUrl);
      return;
    }
    if (message.type === "copy") {
      await vscode.env.clipboard.writeText(message.text);
      return;
    }
    if (message.type === "openDefinition") {
      const definition = this.definitionTargets.get(message.id);
      if (definition) await this.openDefinition(definition);
      return;
    }
    if (message.type === "addToPage") {
      if (this.suggestion)
        await vscode.commands.executeCommand(
          "wintestkit.spy.addToPage",
          this.suggestion,
        );
      return;
    }
    const nodeId = "nodeId" in message ? message.nodeId : undefined;
    if (message.type === "select") {
      if (!restoringPick) this.pickedPoint = undefined;
      this.suggestion = undefined;
      this.selectedNodeId = message.nodeId;
      this.post({ type: "selectionPending", nodeId: message.nodeId });
      this.managedPanel?.select(message.nodeId);
      if (message.path) this.rememberSelection(message.path);
    }
    const title =
      message.type === "expand"
        ? "Loading children"
        : message.type === "select"
          ? "Inspecting object"
          : "Highlighting object";
    await this.loading(
      title,
      2,
      async (phase) => {
        const connection = phase("Connecting to automation server", () =>
          this.connect(),
        );
        const selection =
          message.type === "select" ? ++this.selection : this.selection;
        if (message.type === "select" && nodeId && !nodeId.startsWith("process:")) void this.managedInspector?.select(nodeId);
        const attempt = await connection;
        if (!attempt.client) return;
        const client = attempt.client;
        if (!nodeId) return;
        if (message.type === "select") void this.managedInspector?.select(nodeId);
        if (message.type === "select" && selection !== this.selection) return;
        if (message.type === "select" && nodeId.startsWith("process:")) {
          void this.loadPreview(client, nodeId, selection);
        } else if (message.type === "expand") {
          await phase("Reading child controls", () => this.showChildren(client, nodeId));
        } else if (message.type === "highlight") {
          const highlight = await phase("Highlighting control", () =>
            this.pickedCall(client, nodeId, (id) => client.request<{ outlinedAncestor?: string; outlinedTarget?: string }>("inspect.highlight", {
              nodeId: id,
              bringToFront: this.bringToFront(),
            })).then((result) => result.value),
          );
          if (highlight.outlinedAncestor)
            void vscode.window.showInformationMessage(`${highlight.outlinedTarget ?? "Selected element"} has no on-screen rectangle; outlined ${highlight.outlinedAncestor} instead`);
        } else if (message.type === "select") {
          if (selection !== this.selection) return;
          const properties = await phase("Reading basic properties", () =>
            this.pickedCall(client, nodeId, (id) => client.request<InspectPropertiesResult>("inspect.properties", {
              nodeId: id,
              ...this.includeShown(),
            })).then((result) => result.value),
          );
          if (
            this.disposed ||
            selection !== this.selection ||
            client !== this.client
          )
            return;
          if (isManagedSource(properties.source)) this.managedPanel?.select(nodeId, true);
          this.post({ type: "selected", nodeId, properties });
          this.loadSelectionDetails(client, nodeId, selection);
        }
      },
      nodeId,
      message.type === "select" || message.type === "highlight"
        ? "details"
        : "tree",
    );
  }
  private isBusy(code?: string): boolean { return ["timeout", "dispatcherUnavailable", "busy"].includes(code ?? ""); }
  private cancelDetailsRetry(preserveBusy = false): void {
    clearTimeout(this.retryTimer); this.retryTimer = undefined;
    this.retryGeneration++; this.retryAttempt = 0; this.retryWanted = false;
    if (!preserveBusy) { this.managedRetryNeeded = false; this.treeRetryNeeded = false; this.detailsBusy = false; }
  }
  private scheduleDetailsRetry(): void {
    if (!this.selectedNodeId || !this.client || this.disposed || !(this.view?.visible || this.propertiesView?.visible)) return;
    if (this.retryRunning) { this.retryWanted = true; return; }
    if (this.retryTimer) return;
    const generation = this.retryGeneration;
    // About two minutes of retries; a getter that always times out must not be polled forever.
    if (this.retryAttempt >= DETAILS_RETRY_LIMIT) return;
    const delay = [2000, 4000, 8000][this.retryAttempt++] ?? 10000;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.retryDetails(generation);
    }, delay);
  }
  private async retryDetails(generation: number): Promise<void> {
    const client = this.client, node = this.selectedNodeId, selection = this.selection;
    if (!client || !node || this.retryRunning || generation !== this.retryGeneration) return;
    this.retryRunning = true;
    let busy = false;
    // A busy UI thread that failed the properties read also timed out the .NET values read beside it.
    const managed = this.managedRetryNeeded || this.detailsBusy;
    try {
      const result = await this.pickedCall(client, node, (id) => client.request<InspectPropertiesResult>("inspect.properties", { nodeId: id, full: true }));
      if (generation !== this.retryGeneration) return;
      this.detailsBusy = false;
      this.post({ type: "allProperties", nodeId: result.nodeId, properties: result.value });
      if (this.treeRetryNeeded) {
        const tree = await this.childrenPage(client, node, undefined, true, false);
        if (generation !== this.retryGeneration) return;
        busy = !Array.isArray(tree) && "blocked" in tree && this.isBusy(tree.blocked.code);
      }
      if (managed && this.managedPanel) busy = !await this.managedPanel.retryBusy() || busy;
    } catch (error) { busy = this.isBusy((error as { data?: { code?: string } })?.data?.code); this.detailsBusy = busy; }
    finally {
      this.retryRunning = false;
      const wanted = this.retryWanted; this.retryWanted = false;
      if (generation === this.retryGeneration && selection === this.selection && client === this.client) {
        if (busy) this.scheduleDetailsRetry(); else this.retryAttempt = 0;
      } else if (wanted) this.scheduleDetailsRetry();
    }
  }
  private checkRootProcesses(): void {
    if (!this.loaded || !(this.view?.visible || this.propertiesView?.visible) || !this.rootNodes.length) return;
    const dead = new Set<number>();
    for (const pid of new Set(this.rootNodes.map((node) => node.info.processId).filter((pid): pid is number => !!pid))) {
      try { process.kill(pid, 0); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") dead.add(pid); }
    }
    if (!dead.size) return;
    if (this.appPids.length && this.appPids.every((pid) => dead.has(pid))) {
      this.cancelDetailsRetry(); this.appPids = []; this.appRunning = false; this.targetName = undefined; this.state();
    }
    const nodes = this.rootNodes.filter((node) => !dead.has(node.info.processId ?? 0));
    this.post({ type: "rootsDiff", nodes, revision: this.revision });
  }
  // -- selected object details ---------------------------------------------------------------
  private loadSelectionDetails(client: JsonRpcClient, nodeId: string, selection: number): void {
    // The server answers these one after another and definitions is the slowest, so the properties come first.
    void this.loadAllProperties(client, nodeId, selection);
    void this.loadPreview(client, nodeId, selection);
    void this.loadDefinitions(client, nodeId, selection);
  }
  /**
   * Every UI Automation property and supported pattern of the selected object. The selection was
   * already posted with the cheap read (including the native window facts), so this only completes
   * the list; a result for a selection that has since changed is dropped.
   */
  private async loadAllProperties(client: JsonRpcClient, nodeId: string, selection: number): Promise<void> {
    const current = () =>
      !this.disposed && !this.tutorialActive() && nodeId === this.selectedNodeId &&
      selection === this.selection && client === this.client;
    this.post({ type: "propertiesLoading", nodeId, loading: true });
    try {
      const result = await this.pickedCall(client, nodeId, (id) => client.request<InspectPropertiesResult>("inspect.properties", { nodeId: id, full: true }));
      nodeId = result.nodeId;
      const properties = result.value;
      if (nodeId === this.selectedNodeId && client === this.client) this.post({ type: "allProperties", nodeId, properties });
    } catch (error) {
      // The basic properties are already shown; a failure here only leaves the list short.
      if (current()) {
        const code = (error as { data?: { code?: string } })?.data?.code;
        if (this.isBusy(code)) {
          this.detailsBusy = true;
          this.scheduleDetailsRetry();
          this.log.error(`Spy .NET request to ${this.managedInspector?.targetLabel ?? "target"} could not complete because its UI thread is busy. Spy retries automatically. ${String(error)}`);
        } else this.log.error("Reading all properties failed: " + String(error));
      }
    } finally {
      if (current()) this.post({ type: "propertiesLoading", nodeId, loading: false });
    }
  }
  /** A live capture of the selected object and its window; nothing is saved. */
  private async loadPreview(client: JsonRpcClient, nodeId: string, selection: number): Promise<void> {
    const previewRevision = ++this.previewRevision;
    const current = () =>
      !this.disposed && !this.tutorialActive() && nodeId === this.selectedNodeId &&
      previewRevision === this.previewRevision && selection === this.selection && client === this.client;
    try {
      const response = await this.pickedCall(client, nodeId, (id) => client.request("inspect.preview", { nodeId: id }));
      if (response.nodeId !== nodeId || !current()) return;
      const result = livePreviewImages(response.value);
      if (typeof result === "string") this.post({ type: "objectPreview", nodeId, reason: result });
      else this.post({ type: "objectPreview", nodeId, preview: result });
    } catch (error) {
      if (!current()) return;
      if (isManagedNodeId(nodeId) && this.isStale(error)) {
        this.post({ type: "objectPreview", nodeId, reason: "Inspector session ended. Reconnecting; retry if the object cannot be restored." });
        await this.recoverStale(); return;
      }
      this.log.error(String(error));
      this.post({
        type: "objectPreview",
        nodeId,
        reason: error instanceof RpcError && error.code === -32601
          ? "Previews need a newer wintestkit package in the project's Python environment."
          : "The preview could not be captured: " + (error instanceof Error ? error.message : String(error)),
      });
    }
  }
  // -- element definitions -----------------------------------------------------------------
  private async loadDefinitions(
    client: JsonRpcClient,
    nodeId: string,
    selection: number,
  ): Promise<void> {
    const current = () =>
      !this.disposed &&
      !this.tutorialActive() &&
      selection === this.selection &&
      client === this.client;
    this.definitionTargets = new Map();
    this.post({ type: "definitions", nodeId, state: "loading" });
    try {
      const response = await this.pickedCall(client, nodeId, (id) => client.request<InspectDefinitionsResult>("inspect.definitions", { nodeId: id }));
      nodeId = response.nodeId;
      const result = response.value;
      if (nodeId !== this.selectedNodeId || client !== this.client) return;
      if (!result) {
        this.post({
          type: "definitions",
          nodeId,
          state: "unavailable",
          reason: "The automation server returned no definitions.",
        });
        return;
      }
      this.definitionTargets = new Map(
        result.definitions.map((definition) => [definition.id, definition]),
      );
      this.post({
        type: "definitions",
        nodeId,
        state: "ready",
        definitions: result.definitions,
        errors: result.errors,
        pageCount: result.pageCount,
        appRunning: result.appRunning,
      });
    } catch (error) {
      if (!current()) return;
      this.log.error(String(error));
      this.post({
        type: "definitions",
        nodeId,
        state: "unavailable",
        reason: error instanceof Error ? error.message : String(error),
      });
    }
  }
  private async openDefinition(definition: DefinitionMatch): Promise<void> {
    const document = await vscode.workspace.openTextDocument(
      vscode.Uri.file(definition.file),
    );
    const start = definition.range
      ? new vscode.Position(
          definition.range.start.line,
          definition.range.start.character,
        )
      : new vscode.Position(Math.max(definition.line - 1, 0), 0);
    const end = definition.range
      ? new vscode.Position(
          definition.range.end.line,
          definition.range.end.character,
        )
      : start;
    await vscode.window.showTextDocument(document, {
      selection: new vscode.Range(start, end),
      preview: false,
    });
  }
  // Whether highlighting an object also raises its application window. Off by
  // default: the outline is drawn above every window anyway.
  /** The rows of the Basic view: a user setting, never project state. A setting that is not a list reads as empty. */
  private basicProperties(): string[] {
    const stored = vscode.workspace
      .getConfiguration("wintestkit.spy")
      .get<unknown>(BASIC_SETTING, [...DEFAULT_BASIC_PROPERTIES]);
    return normalizeBasicProperties(stored);
  }
  /** Asks the server to read the pinned UI Automation properties along with the basic ones. */
  private includeShown(): { include?: string[] } {
    const names = basicUiaNames(this.basicProperties());
    return names.length ? { include: names } : {};
  }
  private basicQueue: Promise<void> = Promise.resolve();
  /** Changes to the Basic list run one after another, so each starts from what the one before wrote. */
  private updateBasic(change: () => Promise<void>): Promise<void> {
    const next = this.basicQueue.then(change);
    this.basicQueue = next.catch(() => undefined);
    return next;
  }
  private setBasicProperty(key: string, pinned: boolean): Promise<void> {
    return this.updateBasic(async () => {
      const current = this.basicProperties();
      if (pinned && !current.includes(key) && current.length >= MAX_BASIC_PROPERTIES) {
        // The panel has already drawn it pinned: say why it is not, and put it back.
        this.post({
          type: "error",
          message: "At most " + MAX_BASIC_PROPERTIES + " rows can be pinned to the Basic view. Unpin one first.",
        });
        this.state();
        return;
      }
      const next = pinned ? [...current, ...(current.includes(key) ? [] : [key])] : current.filter((item) => item !== key);
      if (next.length === current.length && next.every((item, index) => item === current[index])) return;
      await vscode.workspace
        .getConfiguration("wintestkit.spy")
        .update(BASIC_SETTING, next, vscode.ConfigurationTarget.Global);
      this.state();
    });
  }
  /** Drops the user's list, so the setting's default applies again. */
  private resetBasicProperties(): Promise<void> {
    return this.updateBasic(async () => {
      await vscode.workspace
        .getConfiguration("wintestkit.spy")
        .update(BASIC_SETTING, undefined, vscode.ConfigurationTarget.Global);
      this.state();
    });
  }
  // -- the split between the Objects tree and the selected object, kept for each workspace ------
  private static readonly treeWidthKey = "wintestkit.spy.treeWidth";
  private treeWidth(): number | undefined {
    const stored = this.memory?.get<unknown>(SpyView.treeWidthKey);
    return typeof stored === "number" && Number.isFinite(stored) && stored >= MIN_TREE_WIDTH && stored <= MAX_TREE_WIDTH
      ? Math.round(stored)
      : undefined;
  }
  private rememberTreeWidth(width: number | null): void {
    void this.memory?.update(SpyView.treeWidthKey, width ?? undefined);
  }
  private bringToFront(): boolean {
    return vscode.workspace
      .getConfiguration("wintestkit.spy")
      .get<boolean>("bringWindowToFront", false);
  }
  private markersEnabled(): boolean {
    return vscode.workspace
      .getConfiguration("wintestkit.spy")
      .get<boolean>("markDefinedObjects", true);
  }
  private trackNodes(
    client: JsonRpcClient,
    nodes: NodeInfo[],
    reset = false,
  ): void {
    if (reset) {
      this.loadedNodeIds.clear();
      this.coverageRun++;
      this.coveragePending.clear();
    }
    for (const node of nodes) this.loadedNodeIds.add(node.nodeId);
    void this.loadCoverage(
      client,
      nodes.map((node) => node.nodeId),
    );
  }
  private scheduleCoverage(): void {
    if (this.tutorialActive()) return;
    clearTimeout(this.coverageTimer);
    this.coverageTimer = setTimeout(() => {
      const client = this.client;
      if (client && this.view?.visible && this.loadedNodeIds.size)
        void this.loadCoverage(client, [...this.loadedNodeIds]);
    }, 600);
  }
  // Marks the nodes that some definition already points at. The server answers within a small time
  // budget and names the nodes it did not finish, which are asked for again until settled.
  private async loadCoverage(
    client: JsonRpcClient,
    nodeIds: string[],
  ): Promise<void> {
    if (!nodeIds.length || this.tutorialActive() || !this.appRunning || !this.markersEnabled()) return;
    const run = this.coverageRun;
    for (const nodeId of nodeIds) this.coveragePending.add(nodeId);
    if (this.coverageWorker?.generation === run) return this.coverageWorker.promise;
    const promise = this.drainCoverage(client, run);
    const worker = { generation: run, promise };
    this.coverageWorker = worker;
    try {
      await promise;
    } finally {
      if (this.coverageWorker === worker) this.coverageWorker = undefined;
    }
  }
  private async drainCoverage(client: JsonRpcClient, run: number): Promise<void> {
    const revision = this.revision;
    const stale = () =>
      this.disposed ||
      this.client !== client ||
      run !== this.coverageRun ||
      revision !== this.revision;
    try {
      for (let round = 0; round < 60 && this.coveragePending.size; round++) {
        if (stale()) return;
        const batch = [...this.coveragePending].slice(0, 500);
        for (const nodeId of batch) this.coveragePending.delete(nodeId);
        const result = await client.request<InspectCoverageResult>(
          "inspect.coverage",
          { nodeIds: batch },
        );
        if (stale() || !result) return;
        const pending = new Set(result.pending.filter((nodeId) => batch.includes(nodeId)));
        this.post({
          type: "coverage",
          nodeIds: batch.filter((id) => !pending.has(id)),
          covered: result.covered,
        });
        for (const nodeId of pending) this.coveragePending.add(nodeId);
      }
    } catch (error) {
      this.log.error(String(error)); // markers are optional: the tree still works without them
    }
  }
  dispose(): void {
    this.trace.dispose();
    this.previewViewer.dispose();
    clearTimeout(this.coverageTimer);
    clearInterval(this.keepaliveTimer);
    clearInterval(this.processTimer);
    this.unbind();
    this.disposed = true;
    [...this.subscriptions, ...this.viewSubscriptions, ...this.propertiesSubscriptions].forEach((subscription) =>
      subscription.dispose(),
    );
    this.view = undefined;
  }
}
