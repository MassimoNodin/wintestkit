import * as vscode from "vscode";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { FlowRunResult } from "../protocol/generated";
import type { FlowStatus } from "./lensModel";
import { RpcError } from "../server/jsonrpc";
import type { ServerManager } from "../server/serverManager";

export interface FlowTarget {
  file: string;
  name: string;
}

// A flow can run for minutes, far longer than the default request timeout.
const FLOW_TIMEOUT_MS = 10 * 60 * 1000;

export function flowKey(target: FlowTarget): string {
  return normalizedPath(target.file) + "::" + target.name;
}

export class FlowRuns implements vscode.Disposable {
  readonly states = new Map<string, FlowStatus>();
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly servers: ServerManager,
    private readonly log: vscode.LogOutputChannel,
  ) {
    this.subscriptions = [
      vscode.commands.registerCommand("wintestkit.runFlow", (target?: FlowTarget) =>
        this.run(target),
      ),
      // Editing a flow makes its last result stale; a running flow keeps its spinner.
      discovery.onDidChange((project) => {
        const root = normalizedPath(project.root.fsPath);
        let cleared = false;
        for (const [key, status] of this.states) {
          if (status.status !== "running" && key.startsWith(root)) {
            this.states.delete(key);
            cleared = true;
          }
        }
        if (cleared) this.changed.fire();
      }),
    ];
  }
  private async run(target?: FlowTarget): Promise<void> {
    if (!target) return;
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    if (!project) return;
    const key = flowKey(target);
    if (this.states.get(key)?.status === "running") {
      void vscode.window.showInformationMessage(
        `${target.name} is already running.`,
      );
      return;
    }
    const pending: FlowStatus = { status: "running" };
    this.set(key, pending);
    try {
      const connection = await this.servers.get(project);
      const result = await connection.client.request<FlowRunResult>(
        "flow.run",
        target,
        FLOW_TIMEOUT_MS,
      );
      if (this.states.get(key) === pending) this.set(key, result);
      if (result.status === "passed") {
        vscode.window.setStatusBarMessage(
          `$(pass-filled) Flow ${target.name} passed in ${Math.round(result.durationMs)} ms`,
          5000,
        );
      } else {
        this.log.info(`Flow ${target.name} failed: ${result.message ?? ""}`);
        const choice = await vscode.window.showErrorMessage(
          `Flow ${target.name} failed: ${result.message ?? "unknown error"}`,
          "Show Output",
        );
        if (choice === "Show Output") this.log.show();
      }
    } catch (error) {
      this.states.delete(key);
      this.changed.fire();
      const message =
        error instanceof RpcError && error.code === -32002
          ? "The app isn't running. Launch it, then run the flow again."
          : error instanceof Error
            ? error.message
            : String(error);
      void vscode.window.showErrorMessage(message);
    }
  }
  private set(key: string, status: FlowStatus): void {
    this.states.set(key, status);
    this.changed.fire();
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}
