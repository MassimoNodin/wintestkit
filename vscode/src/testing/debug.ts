import { randomUUID } from "node:crypto";
import * as vscode from "vscode";
import type { Project } from "../server/serverManager";

export function debugConfiguration(
  root: string,
  python: string,
  url: string,
  nodeids: string[],
): vscode.DebugConfiguration {
  return {
    type: "debugpy",
    request: "launch",
    name: "WinTestKit: Debug tests",
    module: "wintestkit",
    args: [
      "run",
      "--events",
      url,
      "--no-report",
      "--no-env-check",
      "--timeout",
      "3600",
      "--",
      ...nodeids,
    ],
    cwd: root,
    python,
    console: "internalConsole",
    justMyCode: true,
    env: { PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
  };
}
export async function runDebugSession(
  project: Project,
  python: string,
  url: string,
  nodeids: string[],
  run: vscode.TestRun,
  token: vscode.CancellationToken,
  sessionEnded: Promise<void>,
): Promise<number | null> {
  if (token.isCancellationRequested) return null;
  if (!vscode.workspace.isTrusted)
    throw new Error("Trust the workspace before debugging WinTestKit.");
  if (!vscode.extensions.getExtension("ms-python.debugpy")) {
    const choice = await vscode.window.showErrorMessage(
      "The Python Debugger extension is required to debug tests.",
      "Install Python Debugger",
    );
    if (choice)
      await vscode.commands.executeCommand(
        "workbench.extensions.installExtension",
        "ms-python.debugpy",
      );
    throw new Error("Install Python Debugger and retry debugging.");
  }
  const marker = randomUUID();
  const configuration = {
    ...debugConfiguration(project.root.fsPath, python, url, nodeids),
    wintestkitRunId: marker,
  };
  let session: vscode.DebugSession | undefined;
  let complete!: (code: number | null) => void;
  const terminated = new Promise<number | null>((resolve) => {
    complete = resolve;
  });
  const subscriptions = [
    vscode.debug.onDidStartDebugSession((started) => {
      if (started.configuration.wintestkitRunId !== marker) return;
      session = started;
      if (token.isCancellationRequested)
        void vscode.debug.stopDebugging(session);
    }),
    vscode.debug.onDidTerminateDebugSession((ended) => {
      if (ended.configuration.wintestkitRunId === marker) complete(0);
    }),
    token.onCancellationRequested(() => {
      if (session) void vscode.debug.stopDebugging(session);
    }),
  ];
  try {
    if (
      !(await vscode.debug.startDebugging(
        vscode.workspace.getWorkspaceFolder(project.root),
        configuration,
        { testRun: run },
      ))
    )
      throw new Error("Python debugger could not start the test session.");
    return await Promise.race([terminated, sessionEnded.then(() => 0)]);
  } finally {
    subscriptions.forEach((subscription) => subscription.dispose());
  }
}
