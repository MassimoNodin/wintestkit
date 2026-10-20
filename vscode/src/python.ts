import { execFile } from "node:child_process";
import * as path from "node:path";
import { PythonExtension } from "@vscode/python-extension";
import * as vscode from "vscode";
import { PYTHON_REQUIREMENT } from "./compatibility";

export async function getInterpreter(
  folder: vscode.Uri,
): Promise<string | undefined> {
  const configured = vscode.workspace
    .getConfiguration("wintestkit", folder)
    .get<string>("pythonPath");
  if (configured?.trim()) return configured.trim();
  const api = await PythonExtension.api();
  const active = api.environments.getActiveEnvironmentPath(folder);
  const resolved = await api.environments.resolveEnvironment(active);
  return resolved?.executable.uri?.fsPath;
}

export interface InterpreterInfo {
  /** The python executable. */
  path: string;
  /** What to call it: its environment's name, or the folder it lives in, such as `.venv`. */
  name: string;
  version?: string;
  /** `wintestkit.pythonPath` is set, so it wins over the Python extension's selection. */
  overridden: boolean;
}

/** The interpreter WinTestKit uses for a folder, in words a person recognises. */
export async function describeInterpreter(
  folder: vscode.Uri,
): Promise<InterpreterInfo | undefined> {
  const configured = vscode.workspace
    .getConfiguration("wintestkit", folder)
    .get<string>("pythonPath")
    ?.trim();
  const api = await PythonExtension.api();
  const resolved = await api.environments.resolveEnvironment(
    configured || api.environments.getActiveEnvironmentPath(folder),
  );
  const executable = configured || resolved?.executable.uri?.fsPath;
  if (!executable) return undefined;
  const prefix = resolved?.executable.sysPrefix;
  const version = resolved?.version;
  return {
    path: executable,
    name:
      resolved?.environment?.name ||
      path.basename(prefix || path.dirname(path.dirname(executable))) ||
      path.basename(executable),
    version: version?.major !== undefined ? `${version.major}.${version.minor}.${version.micro}` : undefined,
    overridden: !!configured,
  };
}

export async function onDidChangeInterpreter(
  listener: (folder?: vscode.Uri) => void,
): Promise<vscode.Disposable> {
  const api = await PythonExtension.api();
  return api.environments.onDidChangeActiveEnvironmentPath((event) =>
    listener(
      event.resource && "uri" in event.resource
        ? event.resource.uri
        : event.resource,
    ),
  );
}

export function checkWintestkit(
  python: string,
): Promise<{ installed: boolean; version?: string }> {
  return new Promise((resolve) => {
    execFile(
      python,
      ["-c", "import wintestkit;print(wintestkit.__version__)"],
      { timeout: 10000, windowsHide: true },
      (error, stdout) => {
        const version = stdout.trim();
        resolve(
          error || !version
            ? { installed: false }
            : { installed: true, version },
        );
      },
    );
  });
}

export async function runTerminal(
  folder: vscode.Uri,
  args: string[],
): Promise<void> {
  if (!vscode.workspace.isTrusted)
    throw new Error("Trust the workspace before running WinTestKit.");
  const python = await getInterpreter(folder);
  if (!python) throw new Error("Select a Python interpreter first.");
  const terminal = vscode.window.createTerminal({
    name: "WinTestKit",
    cwd: folder.fsPath,
    shellPath: python,
    shellArgs: args,
  });
  terminal.show();
}

export async function installArguments(): Promise<string[]> {
  return ["-m", "pip", "install", "--upgrade", "--force-reinstall", PYTHON_REQUIREMENT];
}
