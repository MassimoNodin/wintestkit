import * as assert from "node:assert/strict";
import * as path from "node:path";
import * as vscode from "vscode";
import type { ExtensionApi } from "../../../src/extension";

suite("WinTestKit activation", () => {
  test("discovers Calculator pages and exposes locator CodeLens without launching an app", async () => {
    const extension = vscode.extensions.getExtension<ExtensionApi>("wintestkit.wintestkit");
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
    const pages = api.elements.getChildren();
    assert.ok(
      pages.some((node: { label: string }) => node.label === "ScientificPage"),
    );
    assert.ok(
      pages.some((node: { label: string }) => node.label === "NavigationPane"),
      "components are listed as pages",
    );
    const flows = api.elements.getChildren(undefined, "flows");
    assert.ok(
      flows.some((node: { children: { label: string }[] }) =>
        node.children.some((child) => child.label === "open_page"),
      ),
    );
    const tests = [...api.tests.items.values()];
    assert.ok(
      tests.some((item) => item.label === "test_add_one"),
    );
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("wintestkit.spy.refresh"));
    assert.ok(commands.includes("wintestkit.checkPage"));
    assert.ok(commands.includes("wintestkit.openSettings"));
    assert.equal(api.tests.controller.id, "wintestkit");
  });
});
