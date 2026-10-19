import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as vscode from "vscode";
import type { Projects } from "./projects";
import { checkWintestkit, getInterpreter } from "./python";

const execute = promisify(execFile);

/**
 * The workspace folder setup works on: the only one, the one the active file is in, or the one the
 * user picks. Undefined when there is none or the user backs out.
 */
export async function chooseWorkspaceFolder(): Promise<vscode.Uri | undefined> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length <= 1) return folders[0]?.uri;
  const active = vscode.window.activeTextEditor?.document.uri;
  const own = active && vscode.workspace.getWorkspaceFolder(active);
  if (own) return own.uri;
  const picked = await vscode.window.showQuickPick(
    folders.map((folder) => ({ label: folder.name, description: folder.uri.fsPath, folder })),
    { placeHolder: "Choose the folder to set up" },
  );
  return picked?.folder.uri;
}

/** Creates the starter project (pages, flows, a smoke test, settings) without overwriting any file. */
export async function initializeProject(
  folder: vscode.Uri,
  projects: Projects,
  log: vscode.LogOutputChannel,
): Promise<void> {
  if (!vscode.workspace.isTrusted)
    throw new Error("Trust the workspace before initializing WinTestKit.");
  const python = await getInterpreter(folder);
  if (!python) throw new Error("Select a Python interpreter first.");
  if (!(await checkWintestkit(python)).installed)
    throw new Error("Install the wintestkit package first.");
  const result = await execute(python, ["-m", "wintestkit", "init", folder.fsPath], {
    cwd: folder.fsPath,
    windowsHide: true,
    timeout: 30000,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  if (result.stdout) log.info(result.stdout);
  if (result.stderr) log.warn(result.stderr);
  await projects.refresh();
}
