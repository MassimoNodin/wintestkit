import * as path from "node:path";
import * as vscode from "vscode";
import { chooseWorkspaceFolder } from "../init";
import { cleanReset, planReset } from "./resetFiles";

export function registerDevReset(
  context: vscode.ExtensionContext,
  prepare: () => Promise<void>,
  busy: () => boolean,
): void {
  let resetting = false;
  context.subscriptions.push(vscode.commands.registerCommand("wintestkit.dev.resetRepository", async () => {
    if (resetting) return;
    resetting = true;
    try {
      if (!vscode.workspace.isTrusted) throw new Error("Trust the workspace before resetting it.");
      if (busy()) throw new Error("Wait for WinTestKit installation or project initialization to finish before resetting.");
      const folder = await chooseWorkspaceFolder();
      if (!folder || folder.scheme !== "file") return;
      const folders = vscode.workspace.workspaceFolders ?? [];
      if (folders.length !== 1)
        throw new Error("Open the repository by itself before resetting workspace-wide introduction state.");
      const plan = await planReset(folder.fsPath);
      const dirty = () => vscode.workspace.textDocuments.some((document) => {
        if (!document.isDirty || document.uri.scheme !== "file") return false;
        const relative = path.relative(plan.root, document.uri.fsPath);
        return relative !== ".." && !relative.startsWith(".." + path.sep) && !path.isAbsolute(relative);
      });
      if (dirty()) throw new Error("Save or close unsaved files in this repository before resetting.");
      const preview = [...plan.remove, ...(plan.pyproject ? ["pyproject.toml (remove WinTestKit/starter pytest configuration)"] : [])];
      const choice = await vscode.window.showWarningMessage(
        "Reset this repository for WinTestKit introduction testing?",
        { modal: true, detail: plan.root + "\n\nBack up outside the repository, then remove:\n" +
          (preview.join("\n") || "No generated files found.") +
          "\n\nEntire pages, flows and tests folders are included, including custom code. Git history, .gitignore, the Python environment and unrelated configuration are kept. WinTestKit workspace state is cleared and VS Code reloads." },
        "Back Up and Reset",
      );
      if (choice !== "Back Up and Reset") return;
      if (!vscode.workspace.isTrusted || busy() || dirty())
        throw new Error("Workspace changed while confirming reset. Save files, finish setup operations and try again.");
      await prepare();
      const backup = await cleanReset(plan);
      for (const key of context.workspaceState.keys())
        if (key.startsWith("wintestkit.")) await context.workspaceState.update(key, undefined);
      await vscode.window.showInformationMessage("Repository reset. Backup: " + backup + ". Reloading to restart the introduction.");
      await vscode.commands.executeCommand("workbench.action.reloadWindow");
    } catch (error) {
      await vscode.window.showErrorMessage(String(error));
    } finally {
      resetting = false;
    }
  }));
}
