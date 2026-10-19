import * as vscode from "vscode";

export const CLEAR_RESULTS_COMMAND = "testing.clearTestResults";

export function registerClearResults(
  prepare: () => () => Promise<void>,
): vscode.Disposable {
  let disposed = false;
  let registration: vscode.Disposable;
  const register = () => vscode.commands.registerCommand(CLEAR_RESULTS_COMMAND, async (...args: unknown[]) => {
    const clear = prepare();
    registration.dispose();
    try {
      await vscode.commands.executeCommand(CLEAR_RESULTS_COMMAND, ...args);
      await clear();
    } finally {
      if (!disposed) registration = register();
    }
  });
  registration = register();
  return { dispose: () => { disposed = true; registration.dispose(); } };
}
