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
  NodeInfo,
  SpyHoverNotification,
  SpyPickedNotification,
  Suggestion,
} from "../protocol/generated";
import { parseSpyRequest, type SpyRequest, type SpyResponse } from "./messages";
import { readApplicationIcons } from "./appIcons";

type SpyConnection = { client?: JsonRpcClient; revision: number };

export class SpyView implements vscode.WebviewViewProvider, vscode.Disposable {
  private view?: vscode.WebviewView;
  private client?: JsonRpcClient;
  private project?: Project;
  private picking = false;
  private appRunning = false;
  private targetPids: number[] = [];
  private targetName?: string;
  private showOtherApps = false;
  private revision = 0;
  private scopeRevision = 0;
  private selection = 0;
  private pickRevision = 0;
  private taskId = 0;
  private connecting?: {
    root: string;
    scopeRevision: number;
    promise: Promise<SpyConnection>;
  };
  private disposed = false;
  private suggestion?: Suggestion;
  private selectedNodeId?: string;
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
  ) {
    this.subscriptions = [
      vscode.window.registerWebviewViewProvider("wintestkit.spy", this),
      vscode.commands.registerCommand("wintestkit.spy.startPick", async () => {
        await vscode.commands.executeCommand("wintestkit.spy.focus");
        await this.safe(() => this.startPick());
      }),
      vscode.commands.registerCommand("wintestkit.spy.refresh", () =>
        this.safe(() => this.refresh()),
      ),
      vscode.commands.registerCommand(
        "wintestkit.spy.revealRelocation",
        (path: string) => this.safe(() => this.revealRelocation(path)),
      ),
      projects.onDidChange(() => {
        if (this.view?.visible) void this.safe(() => this.refresh());
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("wintestkit.spy.bringWindowToFront"))
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
            await this.connecting?.promise.catch(() => undefined);
            if (!this.disposed && this.view?.visible) await this.refresh();
          });
        }
      }),
    ];
  }
  async resolveWebviewView(view: vscode.WebviewView): Promise<void> {
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.view = view;
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
        if (view.visible) void this.safe(() => this.refresh());
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
  private post(message: SpyResponse): void {
    if (!this.disposed) void this.view?.webview.postMessage(message);
  }
  private state(): void {
    const project = this.currentProject();
    this.post({
      type: "state",
      picking: this.picking,
      appRunning: this.appRunning,
      targetName: this.targetName ?? project?.name ?? "Test Target",
      targetPids: this.targetPids,
      hasProject: !!this.currentProject(),
      showOtherApps: this.showOtherApps,
      bringToFront: this.bringToFront(),
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
        try {
          await this.refresh();
        } catch (refreshError) {
          this.log.error(String(refreshError));
        }
        this.post({
          type: "error",
          message: "The element is gone; refreshed.",
        });
      } else
        this.post({
          type: "error",
          message: error instanceof Error ? error.message : String(error),
        });
    }
  }
  private unbind(): void {
    const client = this.client;
    this.notifications.forEach((subscription) => subscription.dispose());
    this.notifications = [];
    this.client = undefined;
    this.picking = false;
    this.suggestion = undefined;
    this.revision++;
    this.selection++;
    this.pickRevision++;
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
    this.unbind();
    this.project = project;
    const revision = this.revision;
    const client = (await this.servers.get(project)).client;
    if (this.disposed || revision !== this.revision) return { revision };
    this.client = client;
    this.notifications = [
      client.onNotification("spy.hover", (value) =>
        this.post({ type: "hover", ...(value as SpyHoverNotification) }),
      ),
      client.onNotification("spy.cancelled", () => {
        this.picking = false;
        this.state();
      }),
      client.onNotification("spy.picked", (value) => {
        void this.safe(async () => {
          if (this.client !== client) return;
          const picked = value as SpyPickedNotification;
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
                }),
              );
            },
            picked.node.nodeId,
            "details",
          );
          if (!this.sameReveal(client, treeRevision, selection)) return;
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
              const icons = await phase("Loading application icons", () =>
                readApplicationIcons(roots.map((node) => node.info.processId)),
              );
              if (!this.sameReveal(client, treeRevision, selection))
                return false;
              this.post({ type: "rootIcons", icons });
              const rootIndex = properties.ancestors.findIndex((ancestor) =>
                roots.some((root) => root.nodeId === ancestor.nodeId),
              );
              const ancestors =
                rootIndex < 0 ? [] : properties.ancestors.slice(rootIndex);
              for (const ancestor of ancestors) {
                if (!this.sameReveal(client, treeRevision, selection))
                  return false;
                const nodes = await phase(
                  "Loading " +
                    (ancestor.info.name || ancestor.info.controlType),
                  () =>
                    client.request<NodeInfo[]>("inspect.children", {
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
          this.post({
            type: "picked",
            ...picked,
            ancestors: properties.ancestors,
          });
          this.post({
            type: "selected",
            nodeId: picked.node.nodeId,
            properties,
            suggestion: picked.suggestion,
          });
          void this.loadDefinitions(client, picked.node.nodeId, selection);
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
    const scopeRevision = this.scopeRevision;
    const showOtherApps = this.showOtherApps;
    await this.loading("Loading objects", 4, async (phase) => {
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
      const status = await phase("Checking application", () =>
        client.request<AppStatusResult>("app.status"),
      );
      if (this.disposed || !this.sameScope(scopeRevision, revision)) return;
      const nodes = await phase("Reading root windows", () =>
        this.requestRoots(client, showOtherApps),
      );
      if (this.disposed || !this.sameScope(scopeRevision, revision)) return;
      this.appRunning = status.running;
      this.targetPids = status.pids;
      this.targetName = status.running ? status.mainWindowTitle : undefined;
      this.state();
      this.post({ type: "roots", nodes });
      this.trackNodes(client, nodes, true);
      const icons = await phase("Loading application icons", () =>
        readApplicationIcons(nodes.map((node) => node.info.processId)),
      );
      if (this.disposed || !this.sameScope(scopeRevision, revision)) return;
      this.post({ type: "rootIcons", icons });
    });
  }
  /** Resolve a diagnostic path against a fresh, bounded UIA snapshot before revealing it. */
  private async revealRelocation(path: string): Promise<void> {
    const parts = path.split(" › ").map((part) => part.trim()).filter(Boolean);
    if (!parts.length || parts.length > 12) throw new Error("Invalid relocation path.");
    const connection = await this.connect();
    if (!connection.client) throw new Error("No active WinTestKit project.");
    const client = connection.client;
    const status = await client.request<AppStatusResult>("app.status");
    if (!status.running) throw new Error("Start the target app before revealing a relocated element.");
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
    const walk = async (node: NodeInfo, ancestors: NodeInfo[], depth: number) => {
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
        ? chain.length === parts.length && chain.every((item, index) => short(item) === parts[index])
        : pathStart >= 0 && chain.slice(pathStart).every((item, index) => short(item) === parts[index]);
      if (pathMatches)
        matches.push({ node, ancestors });
      if (depth >= parts.length || !node.hasChildren) return;
      const children = await client.request<NodeInfo[]>("inspect.children", { nodeId: node.nodeId });
      for (const child of children) await walk(child, chain, depth + 1);
    };
    for (const root of roots) await walk(root, [], 1);
    if (exhausted) throw new Error("Relocation search exceeded its safety limit; narrow the desktop scope and try again.");
    if (matches.length !== 1)
      throw new Error(matches.length ? "Relocation path is ambiguous in the current UI." : "Relocation path is no longer present; refresh Spy.");
    const target = matches[0];
    const revision = ++this.revision;
    this.selection++;
    this.post({ type: "roots", nodes: roots });
    this.trackNodes(client, roots, true);
    for (const ancestor of target.ancestors) {
      const children = await client.request<NodeInfo[]>("inspect.children", { nodeId: ancestor.nodeId });
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
    this.scopeRevision++;
    this.revision++;
    this.selection++;
    this.suggestion = undefined;
  }
  private requestRoots(
    client: JsonRpcClient,
    showOtherApps = this.showOtherApps,
  ): Promise<NodeInfo[]> {
    return showOtherApps
      ? client.request<NodeInfo[]>("inspect.roots", { includeOtherApps: true })
      : client.request<NodeInfo[]>("inspect.roots");
  }
  async refreshForProject(project: Project): Promise<void> {
    if (
      this.view?.visible &&
      this.currentProject()?.root.toString() === project.root.toString()
    )
      await this.safe(() => this.refresh());
  }
  private async startPick(): Promise<void> {
    await this.loading("Starting picker", 2, async (phase) => {
      const attempt = await phase("Connecting to automation server", () =>
        this.connect(),
      );
      if (!attempt.client) return;
      const client = attempt.client;
      const revision = ++this.pickRevision;
      await phase("Starting element picker", () => client.request("spy.start"));
      if (
        revision !== this.pickRevision ||
        this.client !== client ||
        this.disposed
      )
        return;
      this.picking = true;
      this.state();
    });
  }
  private async stopPick(): Promise<void> {
    this.pickRevision++;
    this.picking = false;
    this.state();
    if (this.client) await this.client.request("spy.stop");
  }
  private async handle(message: SpyRequest): Promise<void> {
    if (message.type === "chooseApp") {
      await vscode.commands.executeCommand("wintestkit.chooseApp");
      return;
    }
    if (message.type === "openGettingStarted") {
      await vscode.commands.executeCommand("wintestkit.openGettingStarted");
      return;
    }
    if (message.type === "ready") {
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
      this.invalidateScope();
      return this.refresh();
    }
    if (message.type === "refresh") return this.refresh();
    if (message.type === "pick") return this.startPick();
    if (message.type === "stopPick") return this.stopPick();
    if (message.type === "copy") {
      await vscode.env.clipboard.writeText(message.text);
      return;
    }
    if (message.type === "openDefinition") {
      const definition = this.definitionTargets.get(message.id);
      if (definition) await this.openDefinition(definition);
      return;
    }
    if (message.type === "insertAssertion") {
      if (message.nodeId !== this.selectedNodeId || !this.definitionTargets.has(message.definitionId)) return;
      await vscode.commands.executeCommand("wintestkit.spy.insertAssertion", {
        name: message.name,
        enabled: message.enabled,
      });
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
      message.type === "select" ? 4 : 2,
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
            client.request<NodeInfo[]>("inspect.children", { nodeId }),
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
            }),
          );
          if (
            this.disposed ||
            selection !== this.selection ||
            client !== this.client
          )
            return;
          this.post({ type: "selected", nodeId, properties });
          const [, suggestion] = await Promise.all([
            phase("Highlighting control", () =>
              client.request("inspect.highlight", {
                nodeId,
                bringToFront: this.bringToFront(),
              }),
            ),
            phase("Generating locator", () =>
              client
                .request<Suggestion>("suggest.locator", { nodeId })
                .catch((error: unknown) => {
                  if (error instanceof RpcError && error.code === -32006)
                    return error.message;
                  throw error;
                }),
            ),
          ]);
          if (
            this.disposed ||
            selection !== this.selection ||
            client !== this.client
          )
            return;
          if (typeof suggestion === "string") {
            this.post({
              type: "suggestionUnavailable",
              nodeId,
              reason: suggestion,
            });
            void this.loadDefinitions(client, nodeId, selection);
            return;
          }
          this.suggestion = suggestion;
          this.post({ type: "suggestion", nodeId, suggestion });
          void this.loadDefinitions(client, nodeId, selection);
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
  // -- element definitions -----------------------------------------------------------------
  private async loadDefinitions(
    client: JsonRpcClient,
    nodeId: string,
    selection: number,
  ): Promise<void> {
    const current = () =>
      !this.disposed && selection === this.selection && client === this.client;
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
  // Whether selecting or highlighting an object also raises its application window. Off by
  // default: the outline is drawn above every window anyway.
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
    }
    for (const node of nodes) this.loadedNodeIds.add(node.nodeId);
    void this.loadCoverage(
      client,
      nodes.map((node) => node.nodeId),
    );
  }
  private scheduleCoverage(): void {
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
    if (!nodeIds.length || !this.appRunning || !this.markersEnabled()) return;
    const run = ++this.coverageRun;
    const revision = this.revision;
    const stale = () =>
      this.disposed ||
      this.client !== client ||
      run !== this.coverageRun ||
      revision !== this.revision;
    let remaining = nodeIds;
    try {
      for (let round = 0; round < 60 && remaining.length; round++) {
        const batch = remaining.slice(0, 500);
        const rest = remaining.slice(500);
        const result = await client.request<InspectCoverageResult>(
          "inspect.coverage",
          { nodeIds: batch },
        );
        if (stale() || !result) return;
        const pending = new Set(result.pending);
        this.post({
          type: "coverage",
          nodeIds: batch.filter((id) => !pending.has(id)),
          covered: result.covered,
        });
        remaining = [...rest, ...result.pending];
      }
    } catch (error) {
      this.log.error(String(error)); // markers are optional: the tree still works without them
    }
  }
  dispose(): void {
    clearTimeout(this.coverageTimer);
    this.unbind();
    this.disposed = true;
    [...this.subscriptions, ...this.viewSubscriptions].forEach((subscription) =>
      subscription.dispose(),
    );
    this.view = undefined;
  }
}
