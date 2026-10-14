import * as vscode from "vscode";
import { createLog } from "./log";

interface CommandContribution {
  command: string;
}

interface ExtensionManifest {
  contributes: { commands: CommandContribution[] };
}

export function activate(context: vscode.ExtensionContext): void {
  const log = createLog();
  context.subscriptions.push(log);
  log.info("WinTestKit activated");

  const manifest = context.extension.packageJSON as ExtensionManifest;
  for (const contribution of manifest.contributes.commands) {
    context.subscriptions.push(
      vscode.commands.registerCommand(contribution.command, () => {
        if (contribution.command === "wintestkit.showOutput") {
          log.show();
        } else {
          log.info(
            contribution.command +
              ": not implemented in the extension scaffold",
          );
        }
      }),
    );
  }

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("wintestkit.elements", {
      getTreeItem: (element: vscode.TreeItem) => element,
      getChildren: () => [],
    }),
    vscode.window.registerWebviewViewProvider("wintestkit.spy", {
      resolveWebviewView: (view: vscode.WebviewView) => {
        view.webview.html =
          "<!DOCTYPE html><html><body><p>The WinTestKit Spy is not implemented yet.</p></body></html>";
      },
    }),
  );

  void vscode.commands.executeCommand(
    "setContext",
    "wintestkit.hasProject",
    false,
  );
  void vscode.commands.executeCommand(
    "setContext",
    "wintestkit.appRunning",
    false,
  );
  void vscode.commands.executeCommand(
    "setContext",
    "wintestkit.picking",
    false,
  );
}

export function deactivate(): void {}
