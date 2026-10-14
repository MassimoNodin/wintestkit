import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import { ServerManager, type Project } from "../server/serverManager";
import { JsonRpcClient, RpcError } from "../server/jsonrpc";
import type {
  AppStatusResult,
  InspectPropertiesResult,
  NodeInfo,
  SpyHoverNotification,
  SpyPickedNotification,
  Suggestion,
} from "../protocol/generated";
import { parseSpyRequest, type SpyRequest, type SpyResponse } from "./messages";

export class SpyView implements vscode.WebviewViewProvider, vscode.Disposable {
  private view?: vscode.WebviewView;
  private client?: JsonRpcClient;
  private project?: Project;
  private picking = false;
  private appRunning = false;
  private revision = 0;
  private selection = 0;
  private pickRevision = 0;
  private connecting?: {
    root: string;
    promise: Promise<JsonRpcClient | undefined>;
  };
  private disposed = false;
  private suggestion?: Suggestion;
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
      projects.onDidChange(() => {
        if (this.view?.visible) void this.safe(() => this.refresh());
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
        if (
          this.client &&
          project.root.toString() === this.project?.root.toString()
        ) {
          this.unbind();
          if (this.view?.visible) void this.safe(() => this.refresh());
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
    this.post({
      type: "state",
      picking: this.picking,
      appRunning: this.appRunning,
      hasProject: !!this.currentProject(),
    });
    void vscode.commands.executeCommand(
      "setContext",
      "wintestkit.picking",
      this.picking,
    );
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
  private async connect(): Promise<JsonRpcClient | undefined> {
    const project = this.currentProject();
    if (!project) {
      this.unbind();
      this.project = undefined;
      this.state();
      return;
    }
    if (
      this.client &&
      this.project?.root.toString() === project.root.toString()
    )
      return this.client;
    const root = project.root.toString();
    if (this.connecting?.root === root) return this.connecting.promise;
    const connecting = { root, promise: this.openConnection(project) };
    this.connecting = connecting;
    try {
      return await connecting.promise;
    } finally {
      if (this.connecting === connecting) this.connecting = undefined;
    }
  }
  private async openConnection(
    project: Project,
  ): Promise<JsonRpcClient | undefined> {
    this.unbind();
    this.project = project;
    const revision = this.revision;
    const client = (await this.servers.get(project)).client;
    if (this.disposed || revision !== this.revision) return;
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
          const picked = value as SpyPickedNotification;
          if (this.client !== client) return;
          await this.stopPick();
          const properties = await client.request<InspectPropertiesResult>(
            "inspect.properties",
            { nodeId: picked.node.nodeId },
          );
          for (const ancestor of [...properties.ancestors].reverse()) {
            const nodes = await client.request<NodeInfo[]>("inspect.children", {
              nodeId: ancestor.nodeId,
            });
            if (this.client !== client) return;
            this.post({ type: "children", nodeId: ancestor.nodeId, nodes });
          }
          if (this.client !== client) return;
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
    return client;
  }
  async refresh(): Promise<void> {
    const client = await this.connect();
    if (!client) {
      this.post({ type: "roots", nodes: [] });
      return;
    }
    const revision = ++this.revision;
    this.selection++;
    this.suggestion = undefined;
    const status = await client.request<AppStatusResult>("app.status");
    const nodes = await client.request<NodeInfo[]>("inspect.roots");
    if (this.disposed || revision !== this.revision) return;
    this.appRunning = status.running;
    this.state();
    this.post({ type: "roots", nodes });
  }
  private async startPick(): Promise<void> {
    const client = await this.connect();
    if (!client) return;
    const revision = ++this.pickRevision;
    await client.request("spy.start");
    if (
      revision !== this.pickRevision ||
      this.client !== client ||
      this.disposed
    )
      return;
    this.picking = true;
    this.state();
  }
  private async stopPick(): Promise<void> {
    this.pickRevision++;
    this.picking = false;
    this.state();
    if (this.client) await this.client.request("spy.stop");
  }
  private async handle(message: SpyRequest): Promise<void> {
    if (message.type === "ready" || message.type === "refresh")
      return this.refresh();
    if (message.type === "pick") return this.startPick();
    if (message.type === "stopPick") return this.stopPick();
    if (message.type === "copy") {
      await vscode.env.clipboard.writeText(message.text);
      return;
    }
    if (message.type === "addToScreen") {
      if (this.suggestion)
        await vscode.commands.executeCommand(
          "wintestkit.spy.addToScreen",
          this.suggestion,
        );
      return;
    }
    const client = await this.connect();
    if (!client) return;
    if (message.type === "launchApp") {
      await client.request("app.launch");
      return this.refresh();
    }
    if (!("nodeId" in message)) return;
    const nodeId = message.nodeId;
    if (message.type === "expand") {
      const nodes = await client.request<NodeInfo[]>("inspect.children", {
        nodeId,
      });
      this.post({ type: "children", nodeId, nodes });
    } else if (message.type === "highlight")
      await client.request("inspect.highlight", { nodeId });
    else if (message.type === "select") {
      const selection = ++this.selection;
      const [properties, suggestion] = await Promise.all([
        client.request<InspectPropertiesResult>("inspect.properties", {
          nodeId,
        }),
        client.request<Suggestion>("suggest.locator", { nodeId }),
        client.request("inspect.highlight", { nodeId }),
      ]);
      if (
        this.disposed ||
        selection !== this.selection ||
        client !== this.client
      )
        return;
      this.suggestion = suggestion;
      this.post({ type: "selected", nodeId, properties, suggestion });
    }
  }
  dispose(): void {
    this.unbind();
    this.disposed = true;
    [...this.subscriptions, ...this.viewSubscriptions].forEach((subscription) =>
      subscription.dispose(),
    );
    this.view = undefined;
  }
}
