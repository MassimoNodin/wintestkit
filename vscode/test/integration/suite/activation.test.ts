import * as assert from "node:assert/strict";
import * as vscode from "vscode";
import * as path from "node:path";

suite("WinTestKit activation", () => {
  test("activates and exposes working scaffold commands", async () => {
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    await extension.activate();
    assert.equal(extension.isActive, true);
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("wintestkit.showOutput"));
    assert.ok(commands.includes("wintestkit.runDoctor"));
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder);
    await vscode.workspace
      .getConfiguration("wintestkit", folder.uri)
      .update(
        "pythonPath",
        path.resolve(
          __dirname,
          "../../../../../python/.venv/Scripts/python.exe",
        ),
        vscode.ConfigurationTarget.Global,
      );
    await vscode.commands.executeCommand("wintestkit.elements.refresh");
    await vscode.commands.executeCommand("wintestkit.showOutput");
    await vscode.commands.executeCommand("wintestkit.runDoctor");
  });
});
