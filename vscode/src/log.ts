import * as vscode from "vscode";

export function createLog(): vscode.LogOutputChannel {
  return vscode.window.createOutputChannel("WinTestKit", { log: true });
}
