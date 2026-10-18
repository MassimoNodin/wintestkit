import * as vscode from "vscode";
import type { AppStatusResult } from "./protocol/generated";
import { ServerManager, type Project } from "./server/serverManager";

export type StartStage = "process" | "window";

export interface ApplicationState {
  running: boolean;
  error?: string;
  pids?: number[];
  mainWindowTitle?: string;
  /** An app action in progress: the server is busy, so this is tracked here, not polled. */
  transition?: {
    /** The action the user asked for; a restart passes through stopping, then starting. */
    action: "launch" | "restart" | "close";
    kind: "starting" | "stopping";
    since: number;
    timeoutMs?: number;
    stage?: StartStage;
  };
  /** The last app action that failed, until the app runs or another action starts. */
  failure?: {
    action: "launch" | "restart" | "close";
    message: string;
    environment?: boolean;
    at: number;
  };
}

export class StatusBar implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<Project>();
  readonly onDidChangeApplication = this.changed.event;
  private readonly applications = new Map<string, ApplicationState>();
  private readonly item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  private readonly subscriptions: vscode.Disposable[];
  private readonly timer: ReturnType<typeof setInterval>;
  private updating = false;
  private pendingRefresh = false;
  private disposed = false;
  constructor(
    private readonly servers: ServerManager,
    private readonly project: () => Project | undefined,
  ) {
    this.item.command = "wintestkit.statusMenu";
    this.item.tooltip = "WinTestKit application and server status";
    this.subscriptions = [
      servers.onDidChange(() => {
        void this.refresh();
      }),
      vscode.window.onDidChangeWindowState((state) => {
        if (state.focused) void this.refresh();
      }),
      vscode.window.onDidChangeActiveTextEditor(() => {
        void this.refresh();
      }),
      vscode.commands.registerCommand("wintestkit.statusMenu", async () => {
        await this.refresh();
        const project = this.project();
        const running = project ? this.applicationState(project)?.running : false;
        const actions = [
          ...(running
            ? [["Restart App", "wintestkit.restartApp"], ["Close App", "wintestkit.closeApp"]]
            : [["Launch App", "wintestkit.launchApp"]]),
          ["Run all tests", "testing.runAll"],
          ["Open Testing view", "wintestkit.openTesting"],
          ["Restart Server", "wintestkit.restartServer"],
          ["Open Last Report", "wintestkit.openReport"],
          ["Check Environment", "wintestkit.runDoctor"],
          ["Show Output", "wintestkit.showOutput"],
        ];
        const choice = await vscode.window.showQuickPick(
          actions.map(([label, command]) => ({ label, command })),
        );
        if (choice) await vscode.commands.executeCommand(choice.command);
      }),
    ];
    this.timer = setInterval(() => {
      if (vscode.window.state.focused) void this.refresh();
    }, 5000);
    void this.refresh();
  }
  async refresh(): Promise<void> {
    if (this.disposed) return;
    if (this.updating) {
      this.pendingRefresh = true;
      return;
    }
    const project = this.project();
    if (!project || !vscode.workspace.isTrusted) {
      this.item.hide();
      await vscode.commands.executeCommand(
        "setContext",
        "wintestkit.appRunning",
        false,
      );
      return;
    }
    this.updating = true;
    let running = false;
    try {
      const connection = await this.servers.get(project);
      const status =
        await connection.client.request<AppStatusResult>("app.status");
      running = status.running;
      const previous = this.applications.get(project.root.toString());
      this.applications.set(project.root.toString(), {
        running,
        pids: status.pids,
        mainWindowTitle: status.mainWindowTitle,
        transition: previous?.transition,
        failure: running ? undefined : previous?.failure,
      });
      this.item.text = `$(beaker) WTK: ${running ? "$(circle-filled) app running" : "$(circle-outline) app stopped"}`;
    } catch (error) {
      this.applications.set(project.root.toString(), {
        running: false,
        error:
          this.servers.state(project) === "not-installed"
            ? "Python package not installed"
            : String(error),
      });
      this.item.text =
        this.servers.state(project) === "not-installed"
          ? "$(beaker) WTK: $(warning) not installed"
          : "$(beaker) WTK: $(error) server error";
    } finally {
      this.updating = false;
      if (!this.disposed) {
        this.changed.fire(project);
        if (this.project()?.root.toString() === project.root.toString()) {
          this.item.show();
          await vscode.commands.executeCommand(
            "setContext",
            "wintestkit.appRunning",
            running,
          );
        } else {
          this.pendingRefresh = true;
        }
        if (this.pendingRefresh) {
          this.pendingRefresh = false;
          void this.refresh();
        }
      }
    }
  }
  applicationState(project: Project): ApplicationState | undefined {
    return this.applications.get(project.root.toString());
  }
  /** Marks an app action as in progress so views can show it (the server cannot answer yet). */
  beginTransition(
    project: Project,
    kind: "starting" | "stopping",
    timeoutMs?: number,
    action: "launch" | "restart" | "close" = kind === "stopping"
      ? "close"
      : "launch",
  ): void {
    const key = project.root.toString();
    const previous = this.applications.get(key) ?? { running: false };
    // A restart closes, then launches: keep its start time across the two steps.
    const continued =
      previous.transition?.action === action ? previous.transition : undefined;
    this.applications.set(key, {
      ...previous,
      failure: undefined,
      transition: {
        action,
        kind,
        since: continued?.since ?? Date.now(),
        timeoutMs,
      },
    });
    this.changed.fire(project);
  }
  setStage(project: Project, stage: StartStage): void {
    const key = project.root.toString();
    const previous = this.applications.get(key);
    if (!previous?.transition) return;
    this.applications.set(key, {
      ...previous,
      transition: { ...previous.transition, stage },
    });
    this.changed.fire(project);
  }
  /** Ends the in-progress action; a message records why it failed. */
  endTransition(
    project: Project,
    failure?: {
      action: "launch" | "restart" | "close";
      message: string;
      environment?: boolean;
    },
  ): void {
    const key = project.root.toString();
    const previous = this.applications.get(key) ?? { running: false };
    this.applications.set(key, {
      ...previous,
      transition: undefined,
      failure: failure ? { ...failure, at: Date.now() } : previous.failure,
    });
    this.changed.fire(project);
  }
  dispose(): void {
    this.disposed = true;
    clearInterval(this.timer);
    this.item.dispose();
    this.changed.dispose();
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
