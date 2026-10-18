import * as vscode from "vscode";
import { assertionLine } from "./assertionModel";

export function registerInsertAssertion(): vscode.Disposable {
  return vscode.commands.registerCommand(
    "wintestkit.spy.insertAssertion",
    async (observed: { name: string; enabled: boolean }) => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.languageId !== "python") {
        await vscode.window.showWarningMessage("Open a Python test and place the cursor where the assertion belongs.");
        return;
      }
      const choices: vscode.QuickPickItem[] = [
        ...(observed.name ? [{ label: "Text", description: `to_have_text(${JSON.stringify(observed.name)})` }] : []),
        { label: "Enabled state", description: observed.enabled ? "to_be_enabled()" : "to_be_disabled()" },
      ];
      const choice = await vscode.window.showQuickPick(choices, { placeHolder: "Choose an assertion from the observed value" });
      if (!choice) return;
      const expression = await vscode.window.showInputBox({
        prompt: "Python expression for this page element in the test",
        placeHolder: "page.submit",
        validateInput: (value) => /^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$/.test(value.trim()) ? undefined : "Enter a dotted Python identifier, for example page.submit.",
      });
      if (!expression) return;
      const line = assertionLine(choice.label === "Text" ? "text" : "enabled", expression.trim(), choice.label === "Text" ? observed.name : observed.enabled);
      const confirm = await vscode.window.showInformationMessage(line, { modal: true, detail: "This uses the observed value. Review it before inserting." }, "Insert");
      if (confirm !== "Insert") return;
      const position = new vscode.Position(editor.selection.active.line, 0);
      const indent = /^\s*/.exec(editor.document.lineAt(position.line).text)?.[0] ?? "";
      const eol = editor.document.eol === vscode.EndOfLine.CRLF ? "\r\n" : "\n";
      const needsImport = !/^\s*from\s+wintestkit\s+import\s+.*\bexpect\b/m.test(editor.document.getText());
      const text = (needsImport ? `${indent}from wintestkit import expect${eol}` : "") + `${indent}${line}${eol}`;
      await editor.edit((edit) => edit.insert(position, text));
    },
  );
}
