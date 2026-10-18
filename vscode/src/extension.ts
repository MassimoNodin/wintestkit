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
import { FlowRuns } from "./editor/flowRuns";
import { TestController } from "./testing/controller";
import { registerInitialize } from "./init";
import { PytestConflict } from "./pytestConflict";
import { ElementsTree } from "./views/elementsTree";
import { Reports } from "./report";
import { SpyView } from "./spy/spyView";
import { registerInsertElement } from "./spy/insertElement";
import { computeInsertion } from "./spy/insertionModel";
import { ConfigurationEditor, settingsEditorId } from "./settings/editor";
import { TestAppView } from "./settings/testApp";
import { readConfiguration } from "./settings/files";

interface CommandContribution {
  command: string;
}

interface ExtensionManifest {
  contributes: { commands: CommandContribution[] };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function activate(context: vscode.ExtensionContext): {
  tests: TestController;
  checks: CheckResultsStore;
  elements: ElementsTree;
  spy: SpyView;
  setup: TestAppView;
  computeInsertion: typeof computeInsertion;
} {
  const log = createLog();
  context.subscriptions.push(log);
  log.info("WinTestKit activated");
  const servers = new ServerManager(log);
  activeServers = servers;
  const projects = new Projects(log);
  const currentProject = (): Project | undefined => {
    const document = vscode.window.activeTextEditor?.document.uri;
    return (document && projects.projectFor(document)) || projects.all[0];
  };
  const status = new StatusBar(servers, currentProject);
  const configuration = new ConfigurationEditor(projects, context.extensionUri);
  const setup = new TestAppView(
    projects,
    status,
    servers,
    context.extensionUri,
  );
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
  const checks = new CheckResultsStore(discovery);
  const flows = new FlowRuns(projects, discovery, servers, log);
  const lenses = new CodeLenses(projects, discovery, checks, flows);
  const elements = new ElementsTree(
    projects,
    discovery,
    checks,
    flows,
    context,
  );
  context.subscriptions.push(elements, flows);
  const spy = new SpyView(projects, servers, context.extensionUri, log);
  context.subscriptions.push(spy);
  context.subscriptions.push(registerInsertElement(projects, discovery, log));
  const reports = new Reports(servers, log);
  const tests = new TestController(projects, discovery, log, reports);
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
    target?: vscode.TreeItem,
    propagateErrors = false,
  ): Promise<void> => {
    const project = target?.resourceUri
      ? projects.projectFor(target.resourceUri)
      : currentProject();
    if (!project) {
      if (propagateErrors) throw new Error("Open a WinTestKit project first.");
      await vscode.window.showInformationMessage(
        "Open a WinTestKit project first.",
      );
      return;
    }
    try {
      await action(project);
    } catch (error) {
      if (propagateErrors) throw error;
      log.error(String(error));
      await vscode.window.showErrorMessage(String(error));
    } finally {
      await status.refresh();
    }
  };
  const changeApp = (
    methods: string[],
    target?: vscode.TreeItem,
    propagateErrors = false,
  ) =>
    withProject(async (project) => {
      const closing = methods.includes("app.close");
      if (closing) {
        const config = await readConfiguration(project.root);
        if (config.launch === "attach") {
          const name = String(config["app.process"] ?? "the attached app").replace(/\.exe$/i, "");
          const answer = await vscode.window.showWarningMessage(
            `Close ${name}? WinTestKit didn't start it, and unsaved work in ${name} will be lost.`,
            { modal: true },
            "Close App",
          );
          if (answer !== "Close App") return;
        }
      }
      if (methods.length > 1) {
        const config = await readConfiguration(project.root);
        if (
          typeof config["app.path"] !== "string" ||
          !config["app.path"].trim()
        )
          throw new Error(
            "Configure an application executable before restarting the app.",
          );
      }
      const connection = await servers.get(project);
      const config = await readConfiguration(project.root).catch(() => ({}));
      const timeout = Number(
        (config as Record<string, unknown>)["app.startup_timeout"],
      );
      const action =
        methods.length > 1
          ? "restart"
          : methods[0] === "app.close"
            ? "close"
            : "launch";
      const starting = connection.client.onNotification(
        "app.starting",
        (value) => {
          const stage = (value as { stage?: string } | undefined)?.stage;
          if (stage === "process" || stage === "window")
            status.setStage(project, stage);
        },
      );
      try {
        for (const method of methods) {
          const closing = method === "app.close";
          status.beginTransition(
            project,
            closing ? "stopping" : "starting",
            closing || !(timeout > 0) ? undefined : timeout * 1000,
            action,
          );
          await connection.client.request(method);
        }
        status.endTransition(project);
      } catch (error) {
        status.endTransition(project, { action, message: errorText(error) });
        throw error;
      } finally {
        starting.dispose();
      }
      await spy.refreshForProject(project);
    }, target, propagateErrors);
  const implemented: Record<string, (target?: vscode.TreeItem) => unknown> = {
    "wintestkit.openTesting": () =>
      vscode.commands.executeCommand("workbench.view.testing.focus"),
    "wintestkit.elements.refresh": () => projects.refresh(),
    "wintestkit.showOutput": () => log.show(),
    "wintestkit.openReport": () => reports.open(currentProject()),
    "wintestkit.launchApp": (target) => changeApp(["app.launch"], target),
    "wintestkit.launchAppStrict": (target) =>
      changeApp(["app.launch"], target, true),
    "wintestkit.closeApp": (target) => changeApp(["app.close"], target),
    "wintestkit.restartApp": (target) =>
      changeApp(["app.close", "app.launch"], target),
    "wintestkit.refreshApp": (target) =>
      withProject((project) => spy.refreshForProject(project), target),
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
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "wintestkit.launchAppStrict",
      (target?: vscode.TreeItem) => implemented["wintestkit.launchAppStrict"](target),
    ),
  );
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
        "wintestkit.runFlow",
        "wintestkit.initProject",
        "wintestkit.openSettings",
        "wintestkit.elements.goTo",
        "wintestkit.spy.startPick",
        "wintestkit.spy.refresh",
      ].includes(contribution.command)
    )
      continue;
    context.subscriptions.push(
      vscode.commands.registerCommand(
        contribution.command,
        (target?: vscode.TreeItem) => {
          if (implemented[contribution.command])
            return implemented[contribution.command](target);
          if (contribution.command === "wintestkit.showOutput") {
            log.show();
          } else {
            log.info(
              contribution.command +
                ": not implemented in the extension scaffold",
            );
          }
        },
      ),
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
