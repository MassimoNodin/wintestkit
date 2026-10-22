import * as vscode from "vscode";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { FlowRunResult } from "../protocol/generated";
import type { FlowStatus } from "./lensModel";
import { RpcError } from "../server/jsonrpc";
import type { ServerManager } from "../server/serverManager";
import { recoverStoppedApp } from "./appRecovery";
import { saveExecutionSources } from "../testing/saveSources";

export interface FlowTarget {
  file: string;
  name: string;
  arguments?: Record<string, string | number | boolean>;
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
    private readonly afterPassed?: (file: string, name: string) => Promise<void>,
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
    const flow = this.discovery.get(project)?.flows?.find((item) => item.name === target.name && normalizedPath(item.file) === normalizedPath(target.file));
    const arguments_ = target.arguments ?? await this.promptArguments(flow?.parameters ?? []);
    if (arguments_ === undefined) return;
    const pending: FlowStatus = { status: "running" };
    this.set(key, pending);
    try {
      if (!(await saveExecutionSources(this.projects, project))) {
        this.states.delete(key);
        this.changed.fire();
        return;
      }
      const connection = await this.servers.get(project);
      let result: FlowRunResult;
      try {
        result = await connection.client.request<FlowRunResult>(
          "flow.run",
          Object.keys(arguments_).length ? { ...target, arguments: arguments_ } : target,
          FLOW_TIMEOUT_MS,
        );
      } catch (error) {
        if (!(error instanceof RpcError) || error.code !== -32002) throw error;
        if (!(await recoverStoppedApp(project, this.servers))) {
          this.states.delete(key);
          this.changed.fire();
          return;
        }
        result = await connection.client.request<FlowRunResult>(
          "flow.run",
          Object.keys(arguments_).length ? { ...target, arguments: arguments_ } : target,
          FLOW_TIMEOUT_MS,
        );
      }
      if (this.states.get(key) === pending) this.set(key, result);
      if (result.status === "passed") {
        await this.afterPassed?.(target.file, target.name);
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
        error instanceof Error
            ? error.message
            : String(error);
      void vscode.window.showErrorMessage(message);
    }
  }
  private async promptArguments(parameters: NonNullable<import("../protocol/generated").FlowEntry["parameters"]>): Promise<Record<string, string | number | boolean> | undefined> {
    const values: Record<string, string | number | boolean> = {};
    for (const parameter of parameters) {
      if (parameter.type === "bool") {
        const options = parameter.required ? ["true", "false"] : [String(parameter.default), "true", "false"];
        const answer = await vscode.window.showQuickPick([...new Set(options)], { title: `Flow parameter: ${parameter.name}`, placeHolder: "Choose true or false" });
        if (answer === undefined) return undefined;
        values[parameter.name] = answer === "true";
        continue;
      }
      const answer = await vscode.window.showInputBox({ title: `Flow parameter: ${parameter.name}`, prompt: `${parameter.type}${parameter.required ? " (required)" : " (optional)"}`, value: parameter.default === undefined ? "" : String(parameter.default), ignoreFocusOut: true });
      if (answer === undefined) return undefined;
      if (answer === "" && !parameter.required) continue;
      if (parameter.type === "str") values[parameter.name] = answer;
      else if (parameter.type === "int" && /^-?\d+$/.test(answer)) values[parameter.name] = Number(answer);
      else if (parameter.type === "float" && answer.trim() && Number.isFinite(Number(answer))) values[parameter.name] = Number(answer);
      else { await vscode.window.showErrorMessage(`Enter a valid ${parameter.type} value for ${parameter.name}.`); return undefined; }
    }
    return values;
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
