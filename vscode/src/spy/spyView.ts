import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import { ServerManager, type Project } from "../server/serverManager";
import { JsonRpcClient, RpcError } from "../server/jsonrpc";
import type {
  AppStatusResult,
  DefinitionMatch,
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
  MAX_SHOWN_PROPERTIES,
  PROPERTY_NAME,
  parseSpyRequest,
  type SpyRequest,
  type SpyResponse,
} from "./messages";
import type { SetupMonitor } from "../setup/monitor";
import { readApplicationIcons } from "./appIcons";
import { livePreviewImages, readObjectPreview, savedPreviewImages } from "./objectPreviews";
import { PreviewViewer } from "./previewViewer";
import { bestMatch, describeSegment, parseSelectionPath, segmentOf, type PathSegment } from "./selectionPath";
import * as path from "node:path";

type SpyConnection = { client?: JsonRpcClient; revision: number };

export class SpyView implements vscode.WebviewViewProvider, vscode.Disposable {
  private view?: vscode.WebviewView;
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
  /** The object the webview shows details for, which a requested locator must belong to. */
  private selectedNodeId?: string;
  private readonly previewViewer = new PreviewViewer();
  /** Whether the tree on screen was read from the current project and is still usable. */
  private loaded = false;
  private appPids: number[] = [];
  private showOtherApps = true;
  private revision = 0;
  private scopeRevision = 0;
  private selection = 0;
  private pickRevision = 0;
  private pickSession?: string;
  private savedDefinition?: { id: string; qualname: string; projectRoot: string };
  private savedSnapshot?: SpyResponse;
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
  // The definitions last shown for the selected object, so the panel can ask to open one by id.
  private definitionTargets = new Map<string, DefinitionMatch>();
  // Tree nodes the panel currently shows, so markers can be refreshed after a page file is saved.
  private loadedNodeIds = new Set<string>();
  private coverageRun = 0;
  private coverageTimer?: NodeJS.Timeout;
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
      vscode.commands.registerCommand("wintestkit.spy.startPick", async () => {
        await vscode.commands.executeCommand("wintestkit.spy.focus");
        await this.safe(() => this.startPick());
      }),
      vscode.commands.registerCommand("wintestkit.spy.refresh", () =>
        this.safe(() => this.refreshLive()),
      ),
      vscode.commands.registerCommand("wintestkit.spy.showDefinition", (value: unknown) =>
        this.safe(() => this.showDefinition(value)),
      ),
      vscode.commands.registerCommand(
        "wintestkit.spy.revealRelocation",
        (path: string) => this.safe(() => this.revealRelocation(path)),
      ),
      projects.onDidChange(() => {
        if (this.view?.visible) void this.safe(() => this.refreshIfStale());
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (
          event.affectsConfiguration("wintestkit.spy.bringWindowToFront") ||
          event.affectsConfiguration("wintestkit.spy.shownProperties")
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
        if (this.savedDefinition) return;
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
  async resolveWebviewView(view: vscode.WebviewView): Promise<void> {
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
      cspSource: view.webview.cspSource,
      nonce,
      css: view.webview
        .asWebviewUri(vscode.Uri.joinPath(assets, "spy.css"))
        .toString(),
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
    this.viewSubscriptions = [
      view.webview.onDidReceiveMessage((value) => {
        const message = parseSpyRequest(value);
        if (message) void this.safe(() => this.handle(message));
      }),
      view.onDidChangeVisibility(() => {
        if (view.visible)
          void this.safe(() =>
            this.savedDefinition ? this.restoreSavedDefinition() : this.tutorialActive() ? this.restoreTutorial() : this.refreshIfStale(),
          );
        else void this.safe(() => this.stopPick());
      }),
      view.onDidDispose(() => {
        if (this.view !== view) return;
        this.view = undefined;
        void this.safe(() => this.stopPick());
      }),
    ];
  }
  private currentProject(): Project | undefined {
    const uri = vscode.window.activeTextEditor?.document.uri;
    return (uri && this.projects.projectFor(uri)) || this.projects.all[0];
  }
  private postTour(): void {
    const focus = this.setup?.focus ?? { dim: false, spyLit: false };
    const tour = this.setup?.tour;
    const tutorial = !this.savedDefinition && tour?.phase === "extras" ? tour : undefined;
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
    return !this.savedDefinition && this.setup?.tour?.phase === "extras";
  }
  private syncTour(): void {
    if (this.savedDefinition) {
      this.postTour();
      return;
    }
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
    if (!this.disposed) void this.view?.webview.postMessage(message);
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
      shownProperties: this.shownProperties(),
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
  ): Promise<T> {
    const taskId = ++this.taskId;
    let completed = 0;
    let finished = false;
    let failed = false;
    const active = new Set<string>();
    const update = (done = false) => {
      if (finished && !done) return;
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
      throw error;
    } finally {
      finished = true;
      update(true);
    }
  }
  private async safe(action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (error) {
      this.log.error(String(error));
      if (error instanceof RpcError && error.code === -32005) {
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
    const client = this.client;
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
      }),
      client.onNotification("spy.picked", (value) => {
        void this.safe(async () => {
          if (!this.currentPick(client, value)) return;
          const picked = value as Omit<SpyPickedNotification, "suggestion"> & { suggestion?: Suggestion };
          const selection = ++this.selection;
          let treeRevision = this.revision;
          const pickedScope = this.showOtherApps;
          const properties = await this.loading(
            "Inspecting picked object",
            2,
            async (phase) => {
              await phase("Stopping element picker", () => this.stopPick());
              return phase("Reading picked control properties", () =>
                client.request<InspectPropertiesResult>("inspect.properties", {
                  nodeId: picked.node.nodeId,
                  includeAncestors: true,
                  ...this.includeShown(),
                }),
              );
            },
            picked.node.nodeId,
            "details",
          );
          if (!this.sameReveal(client, treeRevision, selection)) return;
          let pickedPath: PathSegment[] | undefined;
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
              this.post({ type: "roots", nodes: roots });
              this.trackNodes(client, roots, true);
              this.deferIcons(client, roots, treeRevision);
              const rootIndex = properties.ancestors.findIndex((ancestor) =>
                roots.some((root) => root.nodeId === ancestor.nodeId),
              );
              const ancestors =
                rootIndex < 0 ? [] : properties.ancestors.slice(rootIndex);
              pickedPath = ancestors.length
                ? [...ancestors.map((ancestor) => segmentOf(ancestor.info)), segmentOf(picked.node.info)]
                : undefined;
              for (const ancestor of ancestors) {
                if (!this.sameReveal(client, treeRevision, selection))
                  return false;
                const nodes = await phase(
                  "Loading " +
                    (ancestor.info.name || ancestor.info.controlType),
                  () =>
                    this.enumerate(client, "inspect.children", {
                      nodeId: ancestor.nodeId,
                    }),
                );
                if (!this.sameReveal(client, treeRevision, selection))
                  return false;
                this.post({ type: "children", nodeId: ancestor.nodeId, nodes });
                this.trackNodes(client, nodes);
              }
              return true;
            },
            picked.node.nodeId,
          );
          if (!revealed || !this.sameReveal(client, treeRevision, selection))
            return;
          this.suggestion = picked.suggestion;
          this.selectedNodeId = picked.node.nodeId;
          if (pickedPath) this.rememberSelection(pickedPath);
          this.post({
            type: "picked",
            node: picked.node,
            suggestion: picked.suggestion,
            ancestors: properties.ancestors,
          });
          this.post({
            type: "selected",
            nodeId: picked.node.nodeId,
            properties,
            suggestion: picked.suggestion,
          });
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
        });
      }),
    ];
    return { client, revision };
  }
  async refresh(): Promise<void> {
    if (this.savedDefinition) return this.restoreSavedDefinition();
    if (this.tutorialActive()) return this.ensureTutorial();
    const key = this.scopeRevision + ":" + this.currentProject()?.root.toString();
    if (this.refreshing && this.refreshKey === key) return this.refreshing;
    this.refreshKey = key;
    const pending = this.refreshTree();
    this.refreshing = pending;
    try {
      await pending;
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
  private refreshLive(): Promise<void> {
    this.leaveSavedDefinition();
    return this.refresh();
  }
  private leaveSavedDefinition(): void {
    if (!this.savedDefinition) return;
    this.savedDefinition = undefined;
    this.savedSnapshot = undefined;
    this.invalidateScope();
    this.postTour();
  }
  private async refreshTree(): Promise<void> {
    const scopeRevision = this.scopeRevision;
    const showOtherApps = this.showOtherApps;
    const restore = !this.skipRestore;
    this.skipRestore = false;
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
      const revision = ++this.revision;
      this.selection++;
      this.suggestion = undefined;
      const result = await phase("Refreshing root windows", () =>
        this.enumerateRefresh(client, showOtherApps),
      );
      if (this.disposed || !this.sameScope(scopeRevision, revision)) return;
      const { nodes, status } = result;
      this.appRunning = status.running;
      this.appPids = status.running ? status.pids : [];
      this.targetName = status.running ? status.mainWindowTitle : undefined;
      this.state();
      this.post({ type: "roots", nodes });
      this.loaded = true;
      this.trackNodes(client, nodes, true);
      this.deferIcons(client, nodes, revision);
      if (restore) void this.restoreSelection(client, nodes, revision);
    });
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
  private async restoreSelection(client: JsonRpcClient, roots: NodeInfo[], revision: number): Promise<void> {
    const path = this.recallSelection();
    if (!path?.length) return;
    const selection = this.selection;
    const stale = () =>
      this.disposed || this.client !== client || revision !== this.revision ||
      selection !== this.selection || this.savedDefinition || this.tutorialActive();
    try {
      let candidates = roots;
      let current: NodeInfo | undefined;
      for (let depth = 0; depth < path.length; depth++) {
        if (current) {
          candidates = await this.enumerate(client, "inspect.children", { nodeId: current.nodeId });
          if (stale()) return;
          this.post({ type: "children", nodeId: current.nodeId, nodes: candidates, expanded: true });
          this.trackNodes(client, candidates);
        }
        current = bestMatch(path[depth], candidates);
        if (!current) {
          this.selectionNotFound(path);
          return;
        }
      }
      if (!current || stale()) return;
      await this.handle({ type: "select", nodeId: current.nodeId });
      this.post({ type: "selectionRestored", nodeId: current.nodeId });
    } catch (error) {
      if (!stale()) this.log.error("Could not restore the selection: " + String(error));
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
    const saved = !!this.savedDefinition;
    this.leaveSavedDefinition();
    if (this.setup?.tour?.phase === "extras") {
      if (saved) await this.restoreTutorial();
      return;
    }
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
      await phase("Starting element picker", () => client.request("spy.start", { sessionId }));
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
    if (this.client) await this.client.request("spy.stop");
  }
  private currentPick(client: JsonRpcClient, value: unknown): boolean {
    return !this.disposed && !this.savedDefinition && !this.tutorialActive() &&
      !!this.view?.visible && this.client === client && !!this.pickSession &&
      !!value && typeof value === "object" &&
      (value as { sessionId?: unknown }).sessionId === this.pickSession;
  }
  // Icons belong to the tree, not to what is selected in it: choosing a row (or restoring the
  // previous selection) while they load must not discard them, so only the tree revision counts.
  private deferIcons(client: JsonRpcClient, nodes: NodeInfo[], revision: number): void {
    void readApplicationIcons(nodes.map((node) => node.info.processId)).then((icons) => {
      if (!this.disposed && !this.savedDefinition && this.client === client && revision === this.revision)
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
  private async enumerate(client: JsonRpcClient, method: string, params?: { nodeId?: string; includeOtherApps?: boolean; foregroundForProcessId?: number }): Promise<NodeInfo[]> {
    const revision = this.revision;
    try {
      return await (params ? client.request<NodeInfo[]>(method, params) : client.request<NodeInfo[]>(method));
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
    if (!client || nodeId !== this.selectedNodeId || this.savedDefinition || this.tutorialActive()) return;
    const selection = this.selection;
    const current = () =>
      !this.disposed && !this.savedDefinition && !this.tutorialActive() &&
      client === this.client && selection === this.selection;
    this.post({ type: "suggestionLoading", nodeId });
    try {
      const suggestion = await client.request<Suggestion>("suggest.locator", { nodeId });
      if (!current()) return;
      this.suggestion = suggestion;
      this.post({ type: "suggestion", nodeId, suggestion });
    } catch (error) {
      if (!current()) return;
      if (!(error instanceof RpcError && error.code === -32006)) this.log.error(String(error));
      this.post({ type: "suggestionUnavailable", nodeId, reason: error instanceof Error ? error.message : String(error) });
    }
  }
  private async showDefinition(value: unknown): Promise<void> {
    if (!value || typeof value !== "object") throw new Error("Invalid saved definition.");
    const candidate = value as Record<string, unknown>;
    if (typeof candidate.id !== "string" || typeof candidate.qualname !== "string" || typeof candidate.projectRoot !== "string")
      throw new Error("Invalid saved definition.");
    const project = this.projects.all.find((item) => path.resolve(item.root.fsPath) === path.resolve(candidate.projectRoot as string));
    if (!project) throw new Error("Saved definition is not in a known WinTestKit project.");
    const definition = { id: candidate.id, qualname: candidate.qualname, projectRoot: project.root.fsPath };
    if (this.pickSession && this.client)
      void this.client.request("spy.stop").catch((error: unknown) => this.log.error(String(error)));
    this.savedDefinition = definition;
    this.postTour();
    this.invalidateScope();
    this.pickRevision++;
    this.pickSession = undefined;
    this.picking = false;
    this.definitionTargets.clear();
    this.coveragePending.clear();
    const selection = this.selection;
    this.savedSnapshot = { type: "savedDefinition", id: definition.id, qualname: definition.qualname, reason: "Loading last-test preview..." };
    await vscode.commands.executeCommand("wintestkit.spy.focus");
    if (this.disposed || this.savedDefinition !== definition || selection !== this.selection) return;
    await this.restoreSavedDefinition();
    try {
      const preview = await readObjectPreview(definition.projectRoot, definition.id);
      if (this.disposed || this.savedDefinition !== definition || selection !== this.selection) return;
      this.savedSnapshot = { type: "savedDefinition", id: definition.id, qualname: definition.qualname,
        preview: preview && savedPreviewImages(preview),
        reason: preview ? undefined : "No saved last-test preview is available for this definition." };
    } catch (error) {
      if (this.disposed || this.savedDefinition !== definition || selection !== this.selection) return;
      this.savedSnapshot = { type: "savedDefinition", id: definition.id, qualname: definition.qualname,
        reason: "Saved preview unavailable: " + (error instanceof Error ? error.message : String(error)) };
    }
    await this.restoreSavedDefinition();
  }
  private async restoreSavedDefinition(): Promise<void> {
    if (!this.disposed && this.savedSnapshot) this.post(this.savedSnapshot);
  }
  private async handle(message: SpyRequest): Promise<void> {
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
    if (this.savedDefinition && !["ready", "refresh", "pick", "stopPick", "copy"].includes(message.type)) return;
    if (this.tutorialActive()) {
      if (message.type === "ready") await this.restoreTutorial();
      return;
    }
    if (message.type === "chooseApp") {
      await vscode.commands.executeCommand("wintestkit.chooseApp");
      return;
    }
    if (message.type === "ready") {
      this.postTour();
      if (this.savedDefinition) return this.restoreSavedDefinition();
      if (typeof message.showOtherApps === "boolean")
        this.showOtherApps = message.showOtherApps;
      this.invalidateScope();
      return this.refresh();
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
      this.skipRestore = true;
      this.invalidateScope();
      return this.refresh();
    }
    if (message.type === "refresh") return this.refreshLive();
    if (message.type === "pick") return this.startPick();
    if (message.type === "stopPick") return this.stopPick();
    if (message.type === "pinProperty") {
      await this.pinProperty(message.name, message.pinned);
      return;
    }
    if (message.type === "generateLocator") {
      await this.generateLocator(message.nodeId);
      return;
    }
    if (message.type === "openPreview") {
      await this.previewViewer.show(message.view, message.dataUrl);
      return;
    }
    if (this.savedDefinition && message.type !== "copy") return;
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
      this.suggestion = undefined;
      this.selectedNodeId = message.nodeId;
      if (message.path) this.rememberSelection(message.path);
    }
    const title =
      message.type === "expand"
        ? "Loading children"
        : message.type === "select"
          ? "Inspecting object"
          : message.type === "loadProperties"
            ? "Loading all properties"
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
        const attempt = await connection;
        if (!attempt.client) return;
        const client = attempt.client;
        if (!nodeId) return;
        if (
          (message.type === "select" || message.type === "loadProperties") &&
          selection !== this.selection
        )
          return;
        if (message.type === "expand") {
          const scopeRevision = this.scopeRevision;
          const treeRevision = this.revision;
          const nodes = await phase("Reading child controls", () =>
            this.enumerate(client, "inspect.children", { nodeId }),
          );
          if (
            this.client === client &&
            scopeRevision === this.scopeRevision &&
            treeRevision === this.revision
          ) {
            this.post({ type: "children", nodeId, nodes });
            this.trackNodes(client, nodes);
          }
        } else if (message.type === "highlight") {
          await phase("Highlighting control", () =>
            client.request("inspect.highlight", {
              nodeId,
              bringToFront: this.bringToFront(),
            }),
          );
        } else if (message.type === "loadProperties") {
          this.post({ type: "propertiesLoading", nodeId, loading: true });
          try {
            const properties = await phase(
              "Reading all properties and patterns",
              () =>
                client.request<InspectPropertiesResult>("inspect.properties", {
                  nodeId,
                  full: true,
                }),
            );
            if (
              !this.disposed &&
              selection === this.selection &&
              client === this.client
            )
              this.post({ type: "allProperties", nodeId, properties });
          } finally {
            if (
              !this.disposed &&
              selection === this.selection &&
              client === this.client
            )
              this.post({ type: "propertiesLoading", nodeId, loading: false });
          }
        } else if (message.type === "select") {
          if (selection !== this.selection) return;
          const properties = await phase("Reading basic properties", () =>
            client.request<InspectPropertiesResult>("inspect.properties", {
              nodeId,
              ...this.includeShown(),
            }),
          );
          if (
            this.disposed ||
            selection !== this.selection ||
            client !== this.client
          )
            return;
          this.post({ type: "selected", nodeId, properties });
          this.loadSelectionDetails(client, nodeId, selection);
        }
      },
      nodeId,
      message.type === "select" ||
        message.type === "highlight" ||
        message.type === "loadProperties"
        ? "details"
        : "tree",
    );
  }
  // -- selected object details ---------------------------------------------------------------
  private loadSelectionDetails(client: JsonRpcClient, nodeId: string, selection: number): void {
    void this.loadDefinitions(client, nodeId, selection);
    void this.loadPreview(client, nodeId, selection);
  }
  /** A live capture of the selected object and its window; nothing is saved. */
  private async loadPreview(client: JsonRpcClient, nodeId: string, selection: number): Promise<void> {
    const current = () =>
      !this.disposed && !this.savedDefinition && !this.tutorialActive() &&
      selection === this.selection && client === this.client;
    try {
      const result = livePreviewImages(await client.request("inspect.preview", { nodeId }));
      if (!current()) return;
      if (typeof result === "string") this.post({ type: "objectPreview", nodeId, reason: result });
      else this.post({ type: "objectPreview", nodeId, preview: result });
    } catch (error) {
      if (!current()) return;
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
      const result = await client.request<InspectDefinitionsResult>(
        "inspect.definitions",
        { nodeId },
      );
      if (!current()) return;
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
  /** The properties the user pinned to the default list: a user setting, never project state. */
  private shownProperties(): string[] {
    const stored = vscode.workspace
      .getConfiguration("wintestkit.spy")
      .get<unknown>("shownProperties", []);
    if (!Array.isArray(stored)) return [];
    return [
      ...new Set(
        stored.filter(
          (name): name is string => typeof name === "string" && PROPERTY_NAME.test(name),
        ),
      ),
    ].slice(0, MAX_SHOWN_PROPERTIES);
  }
  /** Asks the server to read the pinned properties along with the basic ones. */
  private includeShown(): { include?: string[] } {
    const shown = this.shownProperties();
    return shown.length ? { include: shown } : {};
  }
  private async pinProperty(name: string, pinned: boolean): Promise<void> {
    const current = this.shownProperties();
    if (pinned && !current.includes(name) && current.length >= MAX_SHOWN_PROPERTIES) {
      // The panel has already drawn it pinned: say why it is not, and put it back.
      this.post({
        type: "error",
        message: "At most " + MAX_SHOWN_PROPERTIES + " properties can be pinned. Unpin one first.",
      });
      this.state();
      return;
    }
    const next = pinned
      ? [...new Set([...current, name])].slice(0, MAX_SHOWN_PROPERTIES)
      : current.filter((item) => item !== name);
    if (next.length === current.length && next.every((item, index) => item === current[index])) return;
    await vscode.workspace
      .getConfiguration("wintestkit.spy")
      .update("shownProperties", next, vscode.ConfigurationTarget.Global);
    this.state();
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
    if (!nodeIds.length || this.savedDefinition || this.tutorialActive() || !this.appRunning || !this.markersEnabled()) return;
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
    this.previewViewer.dispose();
    clearTimeout(this.coverageTimer);
    this.unbind();
    this.disposed = true;
    [...this.subscriptions, ...this.viewSubscriptions].forEach((subscription) =>
      subscription.dispose(),
    );
    this.view = undefined;
  }
}
