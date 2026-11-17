import { execFile } from "node:child_process";
import * as path from "node:path";
import { PythonExtension } from "@vscode/python-extension";
import * as vscode from "vscode";
import { ALLOW_PRERELEASE, PYTHON_REQUIREMENT, UPGRADE_REQUIREMENT } from "./compatibility";

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
): Promise<{ installed: boolean; version?: string; inspectorVersion?: string }> {
  return new Promise((resolve) => {
    execFile(
      python,
      ["-c", "import wintestkit, importlib.metadata as m; print(wintestkit.__version__); print(next((d.version for d in m.distributions() if d.metadata['Name'].lower().replace('_', '-') == 'wintestkit-inspector'), ''))"],
      { timeout: 10000, windowsHide: true },
      (error, stdout) => {
        const [version, inspectorVersion] = stdout.trim().split(/\r?\n/);
        resolve(
          error || !version
            ? { installed: false }
            : { installed: true, version, ...(inspectorVersion ? { inspectorVersion } : {}) },
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
  return ["-m", "pip", "install", "--upgrade", "--force-reinstall", ...(ALLOW_PRERELEASE ? ["--pre"] : []), UPGRADE_REQUIREMENT];
}

export async function requirePip(python: string, args: string[]): Promise<{ executable: string; args: string[] }> {
  const probe = (executable: string, probeArgs: string[]) => new Promise<Error | null>((resolve) => {
    execFile(executable, probeArgs, { timeout: 10000, windowsHide: true }, (error) => resolve(error));
  });
  const error = await probe(python, ["-I", "-m", "pip", "--version"]);
  if (!error) return { executable: python, args };
  const profile = process.env.USERPROFILE;
  const candidates = ["uv", ...(profile ? [path.join(profile, ".local", "bin", "uv.exe"), path.join(profile, ".cargo", "bin", "uv.exe")] : [])];
  for (const executable of candidates) {
    if (!(await probe(executable, ["--version"]))) {
      return { executable, args: ["pip", "install", "--python", python, "--upgrade",
        "--reinstall-package", "wintestkit", "--reinstall-package", "wintestkit-inspector",
        ...(args.includes("--pre") ? ["--prerelease", "allow"] : []), args.at(-1) ?? PYTHON_REQUIREMENT] };
    }
  }
  const quote = (value: string) => "'" + value.replaceAll("'", "''") + "'";
  const target = args.at(-1) ?? PYTHON_REQUIREMENT;
  throw new Error("Could not run pip in the selected interpreter " + python +
    ". No environment was changed. For a pip-less uv environment, run in PowerShell: uv pip install --python " +
    quote(python) + " --upgrade " + (args.includes("--pre") ? "--prerelease allow " : "") + quote(target) +
    ". Otherwise enable pip in that environment or select an interpreter with pip, then retry. Probe: " + error.message);
}
