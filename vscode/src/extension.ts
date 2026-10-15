import * as vscode from "vscode";
import { createLog } from "./log";
import { installPackage, onDidChangeInterpreter, runTerminal } from "./python";
import { ServerManager, type Project } from "./server/serverManager";
import { StatusBar } from "./statusBar";
import { Projects } from "./projects";
import { DiscoveryStore } from "./discovery/store";
import { CodeLenses } from "./editor/codeLens";
import { CheckDecorations, CheckResultsStore } from "./editor/decorations";
import { HighlightCommands } from "./editor/highlightCommands";
import { TestController } from "./testing/controller";
import { registerInitialize } from "./init";
import { PytestConflict } from "./pytestConflict";
import { ElementsTree } from "./views/elementsTree";
import { Reports } from "./report";
import { SpyView } from "./spy/spyView";
import { registerInsertElement } from "./spy/insertElement";
import { computeInsertion } from "./spy/insertionModel";
import { ConfigurationEditor, settingsEditorId } from "./settings/editor";
import { CurrentSetup } from "./settings/currentSetup";

interface CommandContribution {
  command: string;
}

interface ExtensionManifest {
  contributes: { commands: CommandContribution[] };
}

export function activate(context: vscode.ExtensionContext): {
  tests: TestController;
  checks: CheckResultsStore;
  elements: ElementsTree;
  spy: SpyView;
  setup: CurrentSetup;
  computeInsertion: typeof computeInsertion;
} {
  const log = createLog();
  context.subscriptions.push(log);
  log.info("WinTestKit activated");
  const servers = new ServerManager(log);
  activeServers = servers;
  const projects = new Projects(log);
  const configuration = new ConfigurationEditor(projects, context.extensionUri);
  const setup = new CurrentSetup(projects);
  context.subscriptions.push(
    setup,
    vscode.window.registerCustomEditorProvider(
      settingsEditorId,
      configuration,
      {
        webviewOptions: { retainContextWhenHidden: true },
        supportsMultipleEditorsPerDocument: false,
      },
    ),
    vscode.commands.registerCommand(
      "wintestkit.openSettings",
      (target?: vscode.Uri | vscode.TreeItem) =>
        configuration
          .open(target instanceof vscode.Uri ? target : target?.resourceUri)
          .catch((error) => vscode.window.showErrorMessage(String(error))),
    ),
  );
  const configWatcher = vscode.workspace.createFileSystemWatcher(
    "**/{pyproject.toml,wintestkit.yaml,wintestkit.local.yaml,wintestkit.local.toml}",
  );
  const configTimers = new Map<string, ReturnType<typeof setTimeout>>();
  const reloadConfig = (uri: vscode.Uri) => {
    const project = projects.projectFor(uri);
    if (!project) return;
    const key = project.root.toString();
    const previous = configTimers.get(key);
    if (previous) clearTimeout(previous);
    configTimers.set(
      key,
      setTimeout(() => {
        configTimers.delete(key);
        setup.refresh();
        if (vscode.workspace.isTrusted)
          void servers
            .restart(project)
            .catch((error) =>
              log.error("Configuration reload failed: " + String(error)),
            );
      }, 350),
    );
  };
  context.subscriptions.push(
    configWatcher,
    configWatcher.onDidCreate(reloadConfig),
    configWatcher.onDidChange(reloadConfig),
    configWatcher.onDidDelete(reloadConfig),
    {
      dispose: () => {
        for (const timer of configTimers.values()) clearTimeout(timer);
        configTimers.clear();
      },
    },
  );
  const discovery = new DiscoveryStore(projects, servers, log);
  const lenses = new CodeLenses(projects, discovery);
  const checks = new CheckResultsStore(discovery);
  const elements = new ElementsTree(projects, discovery, checks);
  context.subscriptions.push(elements);
  const spy = new SpyView(projects, servers, context.extensionUri, log);
  context.subscriptions.push(spy);
  context.subscriptions.push(registerInsertElement(projects, discovery, log));
  const reports = new Reports(servers, log);
  const tests = new TestController(projects, discovery, lenses, log, reports);
  context.subscriptions.push(
    registerInitialize(projects, log),
    new PytestConflict(projects, context.workspaceState, log),
  );
  context.subscriptions.push(tests);
  context.subscriptions.push(
    lenses,
    checks,
    new CheckDecorations(checks, context.extensionUri),
    new HighlightCommands(projects, discovery, servers, checks, log),
  );
  const currentProject = (): Project | undefined => {
    const document = vscode.window.activeTextEditor?.document.uri;
    return document ? projects.projectFor(document) : projects.all[0];
  };
  const status = new StatusBar(servers, currentProject);
  context.subscriptions.push(servers, status, projects, discovery);
  let previousProjects: readonly Project[] = [];
  context.subscriptions.push(
    projects.onDidChange((current) => {
      for (const project of previousProjects) {
        if (
          !current.some(
            (candidate) =>
              candidate.root.toString() === project.root.toString(),
          )
        )
          void servers
            .release(project)
            .catch((error) => log.error(String(error)));
      }
      previousProjects = current;
      void status.refresh();
    }),
  );
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
    "wintestkit.elements.refresh": () => projects.refresh(),
    "wintestkit.showOutput": () => log.show(),
    "wintestkit.openReport": () => reports.open(currentProject()),
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
    for (const project of projects.all) {
      if (
        !folder ||
        vscode.workspace.getWorkspaceFolder(project.root)?.uri.toString() ===
          folder.toString()
      )
        void servers
          .restartIfInterpreterChanged(project)
          .catch((error) => log.error(String(error)));
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
        for (const project of projects.all)
          void servers
            .restart(project)
            .catch((error) => log.error(String(error)));
      }
    }),
  );

  const manifest = context.extension.packageJSON as ExtensionManifest;
  for (const contribution of manifest.contributes.commands) {
    if (
      [
        "wintestkit.highlightElement",
        "wintestkit.checkElement",
        "wintestkit.checkPage",
        "wintestkit.runTest",
        "wintestkit.debugTest",
        "wintestkit.initProject",
        "wintestkit.openSettings",
        "wintestkit.elements.goTo",
        "wintestkit.tests.run",
        "wintestkit.tests.debug",
        "wintestkit.spy.startPick",
        "wintestkit.spy.refresh",
      ].includes(contribution.command)
    )
      continue;
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
  void projects.refresh();
  return { tests, checks, elements, spy, setup, computeInsertion };
}

let activeServers: ServerManager | undefined;
export async function deactivate(): Promise<void> {
  const servers = activeServers;
  activeServers = undefined;
  await servers?.shutdown();
}
