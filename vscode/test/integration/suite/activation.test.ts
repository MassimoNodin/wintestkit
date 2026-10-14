import * as assert from "node:assert/strict";
import * as vscode from "vscode";

suite("WinTestKit activation", () => {
  test("activates and exposes working scaffold commands", async () => {
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    await extension.activate();
    assert.equal(extension.isActive, true);
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("wintestkit.showOutput"));
    assert.ok(commands.includes("wintestkit.runDoctor"));
    await vscode.commands.executeCommand("wintestkit.showOutput");
    await vscode.commands.executeCommand("wintestkit.runDoctor");
  });
});
