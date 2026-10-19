import * as vscode from "vscode";
import { createLog } from "./log";
import { onDidChangeInterpreter, runTerminal } from "./python";
import { ServerManager, type Project } from "./server/serverManager";
import { StatusBar } from "./statusBar";
import { Projects } from "./projects";
import { DiscoveryStore } from "./discovery/store";
import { CodeLenses } from "./editor/codeLens";
import { CheckDecorations, CheckResultsStore } from "./editor/decorations";
import { HighlightCommands } from "./editor/highlightCommands";
import { FlowRuns } from "./editor/flowRuns";
import { CheckAfterFlow } from "./editor/checkAfterFlow";
import { ProjectSweep } from "./editor/projectSweep";
import { TestController } from "./testing/controller";
import { registerClearResults } from "./testing/clearResults";
import { Enablement } from "./enablement";
import { PackageInstaller } from "./setup/install";
import { SetupMonitor } from "./setup/monitor";
import { PytestConflict } from "./pytestConflict";
import { ElementsTree } from "./views/elementsTree";
import { SidebarView } from "./views/sidebarView";
import { UnusedDefinitions } from "./views/unusedDefinitions";
import { Reports } from "./report";
import { runNameFrom, testItemFrom } from "./runHistory";
import { SpyView } from "./spy/spyView";
import { registerInsertElement } from "./spy/insertElement";
import { RelocationActions } from "./editor/relocationActions";
import { computeInsertion } from "./spy/insertionModel";
import { ConfigurationEditor, settingsEditorId } from "./settings/editor";
import { TestAppView } from "./settings/testApp";
import type { AppStatusResult } from "./protocol/generated";
import { readConfiguration } from "./settings/files";
import { RpcError } from "./server/jsonrpc";

interface CommandContribution {
  command: string;
}

const RPC_TIMEOUT_OVERHEAD_SECONDS = 5;
const MAX_APP_RPC_TIMEOUT_SECONDS = 24 * 60 * 60;

function appRpcTimeoutMs(
  configured: unknown,
  fallbackSeconds: number,
  setting: string,
): number {
  const value = configured === undefined ? fallbackSeconds : Number(configured);
  if (!Number.isFinite(value) || value <= 0)
    throw new Error(`${setting} must be a finite positive number.`);
  if (value + RPC_TIMEOUT_OVERHEAD_SECONDS > MAX_APP_RPC_TIMEOUT_SECONDS)
    throw new Error(`${setting} is too large; the maximum is ${MAX_APP_RPC_TIMEOUT_SECONDS - RPC_TIMEOUT_OVERHEAD_SECONDS} seconds.`);
  return Math.ceil((value + RPC_TIMEOUT_OVERHEAD_SECONDS) * 1000);
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
  unused: UnusedDefinitions;
  reports: Reports;
  computeInsertion: typeof computeInsertion;
} {
  const log = createLog();
  context.subscriptions.push(log);
  log.info("WinTestKit activated");
  const servers = new ServerManager(log);
  activeServers = servers;
  const enablement = new Enablement(context.workspaceState);
  context.subscriptions.push(enablement);
  const projects = new Projects(log, enablement);
  const currentProject = (): Project | undefined => {
    const document = vscode.window.activeTextEditor?.document.uri;
    return (document && projects.projectFor(document)) || projects.all[0];
  };
  const status = new StatusBar(servers, currentProject);
  const configuration = new ConfigurationEditor(projects, context.extensionUri);
  const reports = new Reports(
    servers,
    log,
    context.globalState,
    context.asAbsolutePath("media/report/template.html"),
  );
  const installer = new PackageInstaller(log, context.workspaceState);
  context.subscriptions.push(installer);
  const setupMonitor = new SetupMonitor(
    projects,
    status,
    context.workspaceState,
    log,
    enablement,
    installer,
    (context.extension.packageJSON as { version?: string }).version,
  );
  const setup = new TestAppView(
    projects,
    status,
    servers,
    context.extensionUri,
    reports,
    setupMonitor,
    enablement,
    log,
  );
  context.subscriptions.push(
    setup,
    setupMonitor,
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
        if (vscode.workspace.isTrusted && enablement.enabled)
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
  const checkAfterFlow = new CheckAfterFlow(projects, discovery, context.workspaceState);
  const projectSweep = new ProjectSweep(projects, discovery, servers, context.workspaceState);
  const flows = new FlowRuns(projects, discovery, servers, log, (file, name) => checkAfterFlow.afterFlow(file, name));
  const lenses = new CodeLenses(projects, discovery, checks, flows);
  const unused = new UnusedDefinitions(projects, discovery);
  const elements = new ElementsTree(
    projects,
    discovery,
    checks,
    flows,
    context,
    reports,
    unused,
    setupMonitor,
  );
  context.subscriptions.push(
    elements,
    new SidebarView(context.extensionUri, setup, elements),
    flows,
    checkAfterFlow,
    projectSweep,
    unused,
  );
  const spy = new SpyView(projects, servers, context.extensionUri, log, setupMonitor);
  context.subscriptions.push(spy);
  context.subscriptions.push(
    registerInsertElement(projects, discovery, log),
  );
  const tests = new TestController(projects, discovery, log, reports, {
    cleared: (project) => status.clearAttachFailure(project),
    notRunning: (project) => status.recordAttachFailure(project),
  });
  context.subscriptions.push(
    new PytestConflict(projects, context.workspaceState, log),
  );
  context.subscriptions.push(tests);
  context.subscriptions.push(registerClearResults(() => tests.prepareClearResults()));
  context.subscriptions.push(
    lenses,
    checks,
    new CheckDecorations(checks, context.extensionUri),
    new HighlightCommands(projects, discovery, servers, checks, log),
    new RelocationActions(checks),
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
  /**
   * The folder setup steps work on. Installing the package and checking the machine come before there
   * is a project, so this falls back to the workspace folder (asking when there are several).
   */
  const setupFolder = async (target?: vscode.TreeItem): Promise<vscode.Uri | undefined> => {
    const project = target?.resourceUri
      ? projects.projectFor(target.resourceUri)
      : currentProject();
    if (project) return project.root;
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (folders.length <= 1) {
      if (!folders.length)
        await vscode.window.showInformationMessage("Open a workspace folder first.");
      return folders[0]?.uri;
    }
    const active = vscode.window.activeTextEditor?.document.uri;
    const own = active && vscode.workspace.getWorkspaceFolder(active);
    if (own) return own.uri;
    const picked = await vscode.window.showQuickPick(
      folders.map((folder) => ({ label: folder.name, description: folder.uri.fsPath, folder })),
      { placeHolder: "Choose the folder to set up" },
    );
    return picked?.folder.uri;
  };
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
      const config = await readConfiguration(project.root);
      if (methods.length > 1) {
        if (
          typeof config["app.path"] !== "string" ||
          !config["app.path"].trim()
        )
          throw new Error(
            "Configure an application executable before restarting the app.",
          );
      }
      const connection = await servers.get(project);
      if (closing) {
        const appStatus = await connection.client.request<AppStatusResult>(
          "app.status",
        );
        if (config.launch === "attach" || !appStatus.owned) {
          const name = String(
            config["app.process"] ?? appStatus.mainWindowTitle ?? "the app",
          ).replace(/\.exe$/i, "");
          const answer = await vscode.window.showWarningMessage(
            `Close ${name}? WinTestKit did not start this process, and unsaved work may be lost.`,
            { modal: true },
            "Close App",
          );
          if (answer !== "Close App") return;
        }
      }
      const startupTimeout = appRpcTimeoutMs(
        config["app.startup_timeout"],
        30,
        "app.startup_timeout",
      );
      const closeTimeout = appRpcTimeoutMs(
        config["app.close_timeout"],
        10,
        "app.close_timeout",
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
            closing ? undefined : startupTimeout - RPC_TIMEOUT_OVERHEAD_SECONDS * 1000,
            action,
          );
          await connection.client.request(
            method,
            {},
            closing ? closeTimeout : startupTimeout,
          );
        }
        status.endTransition(project);
      } catch (error) {
        status.endTransition(project, {
          action,
          message: errorText(error),
          ...(error instanceof RpcError && error.code === -32005
            ? { environment: true }
            : {}),
        });
        throw error;
      } finally {
        starting.dispose();
      }
      await spy.refreshForProject(project);
    }, target, propagateErrors);
  const implemented: Record<string, (target?: vscode.TreeItem, ...args: unknown[]) => unknown> = {
    "wintestkit.chooseApp": () => setup.chooseApp(),
    "wintestkit.openSetup": () => setupMonitor.show(),
    "wintestkit.setup.recheck": () => setupMonitor.recheck(),
    "wintestkit.enable": async () => {
      await enablement.set(true);
      await setupMonitor.show();
    },
    "wintestkit.disable": () => enablement.set(false),
    "wintestkit.openTesting": () =>
      vscode.commands.executeCommand("workbench.view.testing.focus"),
    "wintestkit.elements.refresh": () => projects.refresh(),
    "wintestkit.showOutput": () => log.show(),
    "wintestkit.openReport": () => reports.open(currentProject()),
    "wintestkit.exportReport": () => reports.exportHtml(currentProject()),
    "wintestkit.openPreviousReport": () => reports.openPrevious(),
    "wintestkit.openRunReport": (...args: unknown[]) => {
      const item = testItemFrom(args) as vscode.TestItem | undefined;
      const name = runNameFrom(args);
      const target = item && tests.reportTarget(item);
      // Without a run name nothing identifies the row's run, so let the user choose rather than guess.
      return name
        ? reports.openRun(name, target?.project.root.toString(), target?.nodeid)
        : reports.openPrevious();
    },
    "wintestkit.openTestReport": (...args: unknown[]) => {
      const item = testItemFrom(args) as vscode.TestItem | undefined;
      const target = item && tests.reportTarget(item);
      return reports.openTest(target?.project, target?.nodeid);
    },
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
    "wintestkit.runDoctor": async (target) => {
      const folder = await setupFolder(target);
      if (folder)
        await runTerminal(folder, ["-m", "wintestkit", "--root", folder.fsPath, "doctor"]).catch(
          (error) => vscode.window.showErrorMessage(String(error)),
        );
    },
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
        "wintestkit.checkAfterFlow",
        "wintestkit.sweepProject",
        "wintestkit.openSettings",
        "wintestkit.elements.goTo",
        "wintestkit.spy.startPick",
        "wintestkit.spy.refresh",
        "wintestkit.spy.revealRelocation",
      ].includes(contribution.command)
    )
      continue;
    context.subscriptions.push(
      vscode.commands.registerCommand(
        contribution.command,
        (target?: vscode.TreeItem, ...args: unknown[]) => {
          if (implemented[contribution.command])
            return implemented[contribution.command](target, ...args);
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
  return { tests, checks, elements, spy, setup, unused, reports, computeInsertion };
}

let activeServers: ServerManager | undefined;
export async function deactivate(): Promise<void> {
  const servers = activeServers;
  activeServers = undefined;
  await servers?.shutdown();
}
