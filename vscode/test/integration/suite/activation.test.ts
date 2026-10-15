import * as assert from "node:assert/strict";
import * as path from "node:path";
import * as vscode from "vscode";

suite("WinTestKit activation", () => {
  test("discovers Calculator pages and exposes locator CodeLens without launching an app", async () => {
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    assert.equal(extension.isActive, true);
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
        vscode.ConfigurationTarget.Workspace,
      );
    await vscode.commands.executeCommand("wintestkit.elements.refresh");
    const uri = vscode.Uri.joinPath(folder.uri, "pages", "scientific.py");
    await vscode.window.showTextDocument(uri);
    let highlight: vscode.CodeLens | undefined;
    for (let attempt = 0; attempt < 80; attempt++) {
      const lenses = await vscode.commands.executeCommand<vscode.CodeLens[]>(
        "vscode.executeCodeLensProvider",
        uri,
      );
      highlight = lenses?.find(
        (lens) =>
          lens.command?.command === "wintestkit.highlightElement" &&
          lens.command.arguments?.[0]?.qualname === "ScientificPage.pi",
      );
      if (highlight) break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    assert.ok(
      highlight,
      "discovery populates highlight CodeLens for Calculator",
    );
    const setup = await api.setup.getChildren();
    assert.equal(setup.length, 1);
    assert.equal(setup[0].label, "CalculatorApp");
    assert.equal(setup[0].command.command, "wintestkit.openSettings");
    assert.ok(setup[0].iconPath);
    const pages = api.elements.getChildren();
    assert.ok(
      pages.some((node: { label: string }) => node.label === "ScientificPage"),
    );
    const flows = api.elements.getChildren(undefined, "flows");
    assert.ok(
      flows.some((node: { children: { label: string }[] }) =>
        node.children.some((child) => child.label === "open_page"),
      ),
    );
    const tests = api.elements.getChildren(undefined, "tests");
    assert.ok(
      tests.some((node: { children: { label: string }[] }) =>
        node.children.some((child) => child.label === "test_add_one"),
      ),
    );
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("wintestkit.spy.refresh"));
    assert.ok(commands.includes("wintestkit.checkPage"));
    assert.ok(commands.includes("wintestkit.tests.run"));
    assert.ok(commands.includes("wintestkit.tests.debug"));
  });
});
