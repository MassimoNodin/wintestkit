import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as vscode from "vscode";
import type { Projects } from "./projects";
import { checkWintestkit, getInterpreter, installPackage } from "./python";

const execute = promisify(execFile);
export function registerInitialize(
  projects: Projects,
  log: vscode.LogOutputChannel,
): vscode.Disposable {
  return vscode.commands.registerCommand("wintestkit.initProject", async () => {
    try {
      if (!vscode.workspace.isTrusted)
        throw new Error("Trust the workspace before initializing WinTestKit.");
      const folders = vscode.workspace.workspaceFolders ?? [];
      if (!folders.length) {
        await vscode.window.showInformationMessage(
          "Open a workspace folder first.",
        );
        return;
      }
      const choice =
        folders.length === 1
          ? { folder: folders[0] }
          : await vscode.window.showQuickPick(
              folders.map((folder) => ({
                label: folder.name,
                description: folder.uri.fsPath,
                folder,
              })),
              { placeHolder: "Choose the folder to initialize" },
            );
      if (!choice) return;
      const folder = choice.folder;
      const python = await getInterpreter(folder.uri);
      if (!python) throw new Error("Select a Python interpreter first.");
      if (!(await checkWintestkit(python)).installed) {
        const install = await vscode.window.showInformationMessage(
          "Install the wintestkit package before initializing a project.",
          "Install",
        );
        if (install) await installPackage(folder.uri);
        return;
      }
      const application = await vscode.window.showOpenDialog({
        title: "Select the application .exe (Cancel to use a placeholder)",
        filters: { Applications: ["exe"] },
        canSelectMany: false,
        canSelectFiles: true,
        canSelectFolders: false,
      });
      const args = [
        "-m",
        "wintestkit",
        "init",
        folder.uri.fsPath,
        ...(application?.[0] ? ["--app", application[0].fsPath] : []),
      ];
      const result = await execute(python, args, {
        cwd: folder.uri.fsPath,
        windowsHide: true,
        timeout: 30000,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      });
      if (result.stdout) log.info(result.stdout);
      if (result.stderr) log.warn(result.stderr);
      await projects.refresh();
      await vscode.window.showTextDocument(
        vscode.Uri.joinPath(folder.uri, "pages", "main.py"),
      );
      const next = await vscode.window.showInformationMessage(
        "Project initialized. Run tests from VS Code's Testing view.",
        "Open Testing",
        "Open smoke test",
      );
      if (next === "Open Testing")
        await vscode.commands.executeCommand("wintestkit.openTesting");
      else if (next === "Open smoke test")
        await vscode.window.showTextDocument(
          vscode.Uri.joinPath(folder.uri, "tests", "test_smoke.py"),
        );
    } catch (error) {
      log.error(String(error));
      const choice = await vscode.window.showErrorMessage(
        String(error),
        "Show Output",
      );
      if (choice) log.show();
    }
  });
}
