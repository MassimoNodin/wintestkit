import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import * as vscode from "vscode";
import type { Enablement } from "../enablement";
import type { Projects } from "../projects";
import {
  checkWintestkit,
  describeInterpreter,
  getInterpreter,
  onDidChangeInterpreter,
} from "../python";
import type { Project } from "../server/serverManager";
import { readConfiguration } from "../settings/files";
import { launchModeId } from "../settings/testAppModel";
import type { StatusBar } from "../statusBar";
import {
  blockingStep,
  gatherHealth,
  parseDoctor,
  STEPS,
  type DoctorCheck,
  type Health,
  type HealthProbes,
  type StepId,
  type StepView,
} from "./health";
import type { PackageInstaller } from "./install";
import {
  EXTRA_STEPS,
  hasWork,
  planTour,
  SETUP_STEPS,
  type ExtraStep,
  type SetupCursor,
  type SetupStep,
  type TourContext,
  type TourView,
} from "./tour";
import { SetupTracker, type SetupProblem } from "./tracker";

const PASSED_KEY = "wintestkit.setup.passed";
const COMPLETED_KEY = "wintestkit.tour.completed";
const MODE_KEY = "wintestkit.tour.modeConfirmed";
const CURSOR_KEY = "wintestkit.tour.cursor";

function runDoctor(python: string, root: string): Promise<DoctorCheck[] | undefined> {
  return new Promise((resolve) => {
    execFile(
      python,
      ["-m", "wintestkit", "--root", root, "doctor", "--json"],
      {
        timeout: 30000,
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      },
      // Doctor exits non-zero when a check fails but still prints every check.
      (_error, stdout) => resolve(parseDoctor(String(stdout ?? ""))),
    );
  });
}

/**
 * Keeps the setup guide honest. It re-runs the checks behind each setup step when something relevant
 * changes, and decides what the guided tour in the sidebar shows: the next step on a first run, or the
 * step that stopped working later.
 */
export class SetupMonitor implements vscode.Disposable {
  private readonly tracker: SetupTracker;
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private readonly subscriptions: vscode.Disposable[] = [];
  private current?: Health;
  private views?: Record<StepId, StepView>;
  private config: Record<string, unknown> = {};
  private pythonName?: string;
  private checking?: Promise<void>;
  private checkAgain = false;
  private timer?: ReturnType<typeof setTimeout>;
  private appRunning = false;
  private disposed = false;
  private completed: boolean;
  private modeConfirmed: boolean;
  private closed = false;
  private cursor?: SetupCursor;
  private extra?: ExtraStep;
  constructor(
    private readonly projects: Projects,
    private readonly status: StatusBar,
    private readonly state: vscode.Memento,
    private readonly log: vscode.LogOutputChannel,
    private readonly enablement: Enablement,
    readonly installer: PackageInstaller,
    /** The wintestkit package version this extension was built for. */
    readonly requiredVersion: string | undefined,
  ) {
    this.tracker = new SetupTracker(state.get<StepId[]>(PASSED_KEY, []));
    this.completed = state.get<boolean>(COMPLETED_KEY, false);
    this.modeConfirmed = state.get<boolean>(MODE_KEY, false);
    const cursor = state.get<string>(CURSOR_KEY);
    if (cursor === "complete" || SETUP_STEPS.includes(cursor as SetupStep)) this.cursor = cursor as SetupCursor;
    this.subscriptions.push(
      enablement.onDidChange(() => this.schedule(0)),
      projects.onDidChange(() => this.schedule()),
      installer.onDidChange(() => this.changed.fire()),
      status.onDidChangeApplication(() => {
        const running = !!this.project() && !!status.applicationState(this.project()!)?.running;
        if (running !== this.appRunning) this.schedule();
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("wintestkit")) this.schedule();
      }),
    );
    void onDidChangeInterpreter(() => this.schedule())
      .then((subscription) => {
        if (this.disposed) subscription.dispose();
        else this.subscriptions.push(subscription);
      })
      .catch((error) => log.warn(`Cannot watch the Python interpreter: ${String(error)}`));
    this.schedule(0);
  }

  get health(): Health | undefined {
    return this.current;
  }
  /** The first step WinTestKit cannot work without, while it is not done. */
  get blocker(): { step: StepId; title: string; detail: string } | undefined {
    const health = this.current;
    const step = health && blockingStep(health);
    return step && health
      ? { step, title: STEPS[step].title, detail: health[step].detail }
      : undefined;
  }

  private context(): TourContext | undefined {
    if (!this.current || !this.views) return undefined;
    return {
      health: this.current,
      views: this.views,
      modeConfirmed: this.modeConfirmed,
      completed: this.completed,
      extra: this.extra,
      cursor: this.cursor,
      closed: this.closed,
      installing: this.installer.busy,
      installError: this.installer.error,
      launchMode: launchModeId(this.config.launch),
      pythonName: this.pythonName,
    };
  }
  /** What the guided tour shows now, if anything. */
  get tour(): TourView | undefined {
    const context = this.context();
    return context && this.enablement.enabled ? planTour(context) : undefined;
  }
  /** The tour was closed but there is still something it would help with. */
  get resumable(): boolean {
    const context = this.context();
    return !!context && this.enablement.enabled && this.closed && hasWork(context);
  }

  private project(): Project | undefined {
    const document = vscode.window.activeTextEditor?.document.uri;
    return (document && this.projects.projectFor(document)) || this.projects.all[0];
  }

  private schedule(delay = 800): void {
    if (this.disposed) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      void this.check();
    }, delay);
  }

  private probes(): HealthProbes {
    const project = this.project();
    const folder = project?.root ?? vscode.workspace.workspaceFolders?.[0]?.uri;
    const root = project?.root.fsPath ?? folder?.fsPath ?? "";
    return {
      interpreter: async () => (folder ? getInterpreter(folder) : undefined),
      interpreterExists: (python) => existsSync(python),
      packageInfo: (python) => checkWintestkit(python),
      doctor: (python) => runDoctor(python, root),
      project: async () => {
        if (!project) return undefined;
        const config = await readConfiguration(project.root).catch(() => undefined);
        this.config = config ?? {};
        return { name: project.name, config };
      },
      appRunning: () => !!project && !!this.status.applicationState(project)?.running,
    };
  }

  /** Runs the checks now; a request that arrives while one is running makes it run once more. */
  check(): Promise<void> {
    if (this.checking) {
      this.checkAgain = true;
      return this.checking;
    }
    this.checking = this.run().finally(() => {
      this.checking = undefined;
      if (this.checkAgain && !this.disposed) {
        this.checkAgain = false;
        this.schedule(0);
      }
    });
    return this.checking;
  }

  private async run(): Promise<void> {
    // Until the user enables WinTestKit for this workspace nothing is checked and nothing is shown.
    if (!this.enablement.enabled) {
      this.current = undefined;
      this.views = undefined;
      await this.publishBlocked();
      this.changed.fire();
      return;
    }
    try {
      const project = this.project();
      this.appRunning = !!project && !!this.status.applicationState(project)?.running;
      const health = await gatherHealth(this.probes());
      if (this.disposed) return;
      this.current = health;
      const { announce, passedChanged } = this.tracker.update(health);
      if (passedChanged) void this.state.update(PASSED_KEY, this.tracker.passedSteps());
      this.views = this.tracker.views(health);
      this.pythonName = await this.describePython();
      await this.publishBlocked();
      this.changed.fire();
      if (announce && !this.tour) void this.announce(announce);
    } catch (error) {
      this.log.warn(`Setup check failed: ${String(error)}`);
    }
  }

  private async describePython(): Promise<string | undefined> {
    const folder = this.project()?.root ?? vscode.workspace.workspaceFolders?.[0]?.uri;
    try {
      return folder ? (await describeInterpreter(folder))?.name : undefined;
    } catch {
      return undefined;
    }
  }

  private async markCompleted(): Promise<void> {
    this.completed = true;
    this.modeConfirmed = true;
    this.extra = undefined;
    this.cursor = undefined;
    await this.state.update(COMPLETED_KEY, true);
    await this.state.update(MODE_KEY, true);
    await this.state.update(CURSOR_KEY, undefined);
  }

  /** Hides the other views while WinTestKit is not set up enough to work and the guide is closed. */
  private publishBlocked(): Thenable<unknown> {
    return vscode.commands.executeCommand(
      "setContext",
      "wintestkit.setupBlocked",
      !!this.blocker && !this.tour,
    );
  }

  private async announce(problem: SetupProblem): Promise<void> {
    const choice = await vscode.window.showWarningMessage(
      `WinTestKit setup: ${problem.title} needs attention. ${problem.detail}`,
      "Open WinTestKit",
    );
    if (choice) await this.show();
  }

  /** Brings the sidebar forward with the guide open. */
  async show(): Promise<void> {
    this.resume();
    await vscode.commands.executeCommand("workbench.view.extension.wintestkit");
  }

  /** Re-runs the checks and says what was found. */
  async recheck(): Promise<void> {
    await this.check();
  }

  // -- what the tour's buttons do to the tour itself -------------------------------------------

  private touch(): void {
    void this.publishBlocked();
    this.changed.fire();
  }

  /** The step the tour is showing, among the setup steps. */
  private shownSetupStep(): SetupStep | undefined {
    const step = this.tour?.step;
    return step && (SETUP_STEPS as readonly string[]).includes(step) ? (step as SetupStep) : undefined;
  }

  back(): void {
    if (!this.tour?.canBack) return;
    if (this.extra) {
      this.extra = EXTRA_STEPS[EXTRA_STEPS.indexOf(this.extra) - 1];
      this.cursor = "complete";
    } else {
      const shown = this.tour?.step;
      const from = shown === "complete" ? SETUP_STEPS.length : SETUP_STEPS.indexOf(shown as SetupStep);
      if (from > 0) this.cursor = SETUP_STEPS[from - 1];
    }
    void this.state.update(CURSOR_KEY, this.cursor);
    this.touch();
  }

  next(): void {
    if (this.extra) {
      const index = EXTRA_STEPS.indexOf(this.extra);
      this.extra = EXTRA_STEPS[index + 1] ?? this.extra;
    } else {
      if (!this.tour?.canNext) return;
      const shown = this.shownSetupStep();
      if (shown) {
        this.cursor = SETUP_STEPS[SETUP_STEPS.indexOf(shown) + 1] ?? "complete";
        void this.state.update(CURSOR_KEY, this.cursor);
      }
    }
    this.touch();
  }

  close(): void {
    const step = this.tour?.step;
    if (step === "complete" || this.extra) void this.markCompleted();
    this.closed = true;
    this.touch();
  }

  resume(): void {
    this.closed = false;
    this.touch();
  }

  async confirmMode(): Promise<void> {
    this.modeConfirmed = true;
    await this.state.update(MODE_KEY, true);
    this.touch();
  }

  continueExtras(): void {
    if (this.tour?.step !== "complete") return;
    this.extra = "spy";
    this.touch();
  }

  async finish(): Promise<void> {
    if (this.tour?.step !== "complete" && !this.extra) return;
    await this.markCompleted();
    this.touch();
  }

  async skip(): Promise<void> {
    this.closed = true;
    await this.markCompleted();
    this.touch();
  }

  /** Whether another view should dull itself, and whether Spy's Pick button is the lit one. */
  get focus(): { dim: boolean; spyLit: boolean } {
    const tour = this.tour;
    return { dim: !!tour && tour.phase !== "extras", spyLit: !!tour?.lit.includes("spy") };
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.timer);
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}
