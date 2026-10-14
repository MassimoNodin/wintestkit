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
    const uri = vscode.Uri.joinPath(folder.uri, "screens", "main.py");
    await vscode.window.showTextDocument(uri);
    let lenses: vscode.CodeLens[] = [];
    for (let attempt = 0; attempt < 20; attempt++) {
      lenses =
        (await vscode.commands.executeCommand<vscode.CodeLens[]>(
          "vscode.executeCodeLensProvider",
          uri,
        )) ?? [];
      if (
        lenses.some(
          (lens) => lens.command?.command === "wintestkit.highlightElement",
        )
      )
        break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const highlight = lenses.find(
      (lens) =>
        lens.command?.command === "wintestkit.highlightElement" &&
        lens.command.arguments?.[0]?.qualname === "MainScreen.sign_in",
    );
    assert.ok(highlight, "discovery populates highlight CodeLens");
    try {
      await vscode.commands.executeCommand("wintestkit.launchApp");
      await vscode.commands.executeCommand(
        "wintestkit.highlightElement",
        ...highlight.command!.arguments!,
      );
      assert.equal(
        vscode.languages
          .getDiagnostics(uri)
          .filter((diagnostic) => diagnostic.source === "WinTestKit").length,
        0,
      );
    } finally {
      await vscode.commands.executeCommand("wintestkit.closeApp");
    }
    await vscode.commands.executeCommand("wintestkit.runTest", {
      id: "tests/test_panels.py::test_panel_a_ok",
    });
    const tests = (
      extension.exports as { tests: { lastResults: Map<string, string> } }
    ).tests;
    assert.equal(
      tests.lastResults.get("tests/test_panels.py::test_panel_a_ok"),
      "passed",
    );
  });
});
