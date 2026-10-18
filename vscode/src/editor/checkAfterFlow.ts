import * as vscode from "vscode";
import type { DiscoveryStore } from "../discovery/store";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";

const STATE_KEY = "wintestkit.checkAfterFlow.v1";
export type Binding = { file: string; page: string; flowFile: string; flowName: string };
export function rememberedPageFlows(state: vscode.Memento): Binding[] {
  return state.get<Binding[]>(STATE_KEY, []);
}

/** Explicit per-user bindings from a page class to a navigation flow. */
export class CheckAfterFlow implements vscode.Disposable {
  private readonly registrations: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly state: vscode.Memento,
  ) {
    this.registrations = [vscode.commands.registerCommand(
      "wintestkit.checkAfterFlow",
      (target?: { file: string; page: string }) => this.choose(target),
    )];
  }
  async afterFlow(file: string, name: string): Promise<void> {
    const bindings = rememberedPageFlows(this.state);
    for (const binding of bindings) {
      if (normalizedPath(binding.flowFile) !== normalizedPath(file) || binding.flowName !== name) continue;
      const project = this.projects.projectFor(vscode.Uri.file(binding.file));
      const page = project && this.discovery.get(project)?.pages.find((item) =>
        normalizedPath(item.file) === normalizedPath(binding.file) && item.qualname === binding.page);
      if (page) await vscode.commands.executeCommand("wintestkit.checkPage", { file: page.file, page: page.qualname });
    }
  }
  private async choose(target?: { file: string; page: string }): Promise<void> {
    if (!target) return;
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    const result = project && this.discovery.get(project);
    if (!result) return;
    const flows = (result.flows ?? []).filter((flow) => flow.runnable);
    if (!flows.length) {
      await vscode.window.showInformationMessage("No flows without required arguments are available yet.");
      return;
    }
    const selected = await vscode.window.showQuickPick(flows.map((flow) => ({
      label: flow.name, description: vscode.workspace.asRelativePath(flow.file), flow,
    })), { title: "Check this class after a navigation flow", placeHolder: "Choose a flow that explicitly reaches this page" });
    if (!selected) return;
    const bindings = rememberedPageFlows(this.state).filter((item) =>
      !(normalizedPath(item.file) === normalizedPath(target.file) && item.page === target.page));
    bindings.push({ ...target, flowFile: selected.flow.file, flowName: selected.flow.name });
    await this.state.update(STATE_KEY, bindings);
    await vscode.window.showInformationMessage(`This class will be checked after ${selected.flow.name} completes successfully.`);
  }
  dispose(): void { this.registrations.forEach((item) => item.dispose()); }
}
