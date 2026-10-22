import * as assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import type { ExtensionApi } from "../../../src/extension";

suite("Configuration editor", () => {
  test("opens native YAML editor, protects local files and supports save and undo", async () => {
    await vscode.extensions.getExtension<ExtensionApi>("wintestkit.wintestkit")!.activate();
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "wtk-settings-"));
    const root = vscode.Uri.file(directory);
    const uri = vscode.Uri.joinPath(root, "wintestkit.local.yaml");
    try {
      await fs.writeFile(path.join(directory, ".gitignore"), "custom-rule\n");
      await vscode.commands.executeCommand("wintestkit.openSettings", root);
      const tab = vscode.window.tabGroups.all
        .flatMap((group) => group.tabs)
        .find(
          (tab) =>
            tab.input instanceof vscode.TabInputCustom &&
            tab.input.uri.toString() === uri.toString(),
        );
      assert.ok(tab?.input instanceof vscode.TabInputCustom);
      assert.equal(tab.input.viewType, "wintestkit.configuration");
      const ignored = await fs.readFile(
        path.join(directory, ".gitignore"),
        "utf8",
      );
      assert.ok(ignored.startsWith("custom-rule\n"));
      assert.ok(ignored.includes("wintestkit.local.yaml\n"));
      const document = await vscode.workspace.openTextDocument(uri);
      await vscode.commands.executeCommand("vscode.openWith", uri, "default");
      const original = document.getText();
      const edit = new vscode.WorkspaceEdit();
      edit.replace(
        uri,
        new vscode.Range(
          document.positionAt(0),
          document.positionAt(original.length),
        ),
        "timeout: 22\napp:\n  process: CalculatorApp.exe\n",
      );
      assert.equal(await vscode.workspace.applyEdit(edit), true);
      assert.equal(await document.save(), true);
      assert.match(await fs.readFile(uri.fsPath, "utf8"), /timeout: 22/);
      await vscode.commands.executeCommand("undo");
      assert.equal(document.getText(), original);
      assert.equal(await document.save(), true);
      await vscode.commands.executeCommand("wintestkit.openSettings", root);
      assert.equal(
        await fs.readFile(path.join(directory, ".gitignore"), "utf8"),
        ignored,
      );
    } finally {
      const tabs = vscode.window.tabGroups.all
        .flatMap((group) => group.tabs)
        .filter((tab) => {
          const input = tab.input;
          return (
            (input instanceof vscode.TabInputCustom ||
              input instanceof vscode.TabInputText) &&
            input.uri.fsPath.startsWith(directory)
          );
        });
      await vscode.window.tabGroups.close(tabs);
      await fs.rm(directory, {
        recursive: true,
        force: true,
        maxRetries: 10,
        retryDelay: 200,
      });
    }
  });
});
