import * as path from "node:path";
import Mocha from "mocha";
import * as vscode from "vscode";

export async function run(): Promise<void> {
  const mocha = new Mocha({ ui: "tdd", color: true, timeout: 60000 });
  const only = process.env.WTK_INTEGRATION_ONLY;
  for (const name of ["activation", "settings", "unused", "report", "clearResults"])
    if (!only || only === name) mocha.addFile(path.resolve(__dirname, name + ".test.js"));
  // WinTestKit does nothing in a workspace until it is enabled there.
  await vscode.extensions.getExtension("wintestkit.wintestkit")?.activate();
  await vscode.commands.executeCommand("wintestkit.enable");
  return new Promise((resolve, reject) => {
    mocha.run((failures) => {
      if (failures > 0)
        reject(new Error(failures + " integration tests failed"));
      else resolve();
    });
  });
}
