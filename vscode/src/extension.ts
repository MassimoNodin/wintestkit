import * as vscode from "vscode";
import { createLog } from "./log";
import { installPackage, onDidChangeInterpreter, runTerminal } from "./python";
import { ServerManager, type Project } from "./server/serverManager";
import { StatusBar } from "./statusBar";

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
  const servers = new ServerManager(log);
  activeServers = servers;
  const currentProject = (): Project | undefined => {
    const document = vscode.window.activeTextEditor?.document.uri;
    const folder = document
      ? vscode.workspace.getWorkspaceFolder(document)
      : vscode.workspace.workspaceFolders?.[0];
    return folder ? { root: folder.uri, name: folder.name } : undefined;
  };
  const status = new StatusBar(servers, currentProject);
  context.subscriptions.push(servers, status);
  const withProject = async (
    action: (project: Project) => Promise<unknown>,
  ): Promise<void> => {
    const project = currentProject();
    if (!project) {
      await vscode.window.showInformationMessage(
        "Open a WinTestKit project first.",
      );
      return;
    }
    try {
      await action(project);
      await status.refresh();
    } catch (error) {
      log.error(String(error));
      await vscode.window.showErrorMessage(String(error));
    }
  };
  const implemented: Record<string, () => unknown> = {
    "wintestkit.showOutput": () => log.show(),
    "wintestkit.launchApp": () =>
      withProject(async (project) =>
        (await servers.get(project)).client.request("app.launch"),
      ),
    "wintestkit.closeApp": () =>
      withProject(async (project) =>
        (await servers.get(project)).client.request("app.close"),
      ),
    "wintestkit.restartServer": () =>
      withProject((project) => servers.restart(project)),
    "wintestkit.runDoctor": () =>
      withProject((project) =>
        runTerminal(project.root, [
          "-m",
          "wintestkit",
          "--root",
          project.root.fsPath,
          "doctor",
        ]),
      ),
    "wintestkit.installPackage": () =>
      withProject((project) => installPackage(project.root)),
  };
  void onDidChangeInterpreter((folder) => {
    const project = currentProject();
    if (
      project &&
      (!folder ||
        vscode.workspace.getWorkspaceFolder(project.root)?.uri.toString() ===
          folder.toString())
    ) {
      void servers.restart(project).catch((error) => log.error(String(error)));
    }
  })
    .then((subscription) => {
      if (activeServers === servers) context.subscriptions.push(subscription);
      else subscription.dispose();
    })
    .catch((error) => log.error(String(error)));
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (
        event.affectsConfiguration("wintestkit.pythonPath") ||
        event.affectsConfiguration("wintestkit.server.logLevel")
      ) {
        const project = currentProject();
        if (project)
          void servers
            .restart(project)
            .catch((error) => log.error(String(error)));
      }
    }),
  );

  const manifest = context.extension.packageJSON as ExtensionManifest;
  for (const contribution of manifest.contributes.commands) {
    context.subscriptions.push(
      vscode.commands.registerCommand(contribution.command, () => {
        if (implemented[contribution.command])
          return implemented[contribution.command]();
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

let activeServers: ServerManager | undefined;
export async function deactivate(): Promise<void> {
  const servers = activeServers;
  activeServers = undefined;
  await servers?.shutdown();
}
