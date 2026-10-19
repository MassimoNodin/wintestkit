import type { Health, StepId, StepView } from "./health";

/** The guided setup, in order. `mode` is a choice, not a check; the rest follow the health checks. */
export const SETUP_STEPS = [
  "interpreter",
  "package",
  "machine",
  "project",
  "app",
  "mode",
  "launch",
] as const;
export type SetupStep = (typeof SETUP_STEPS)[number];

/** What is offered once setup is done. */
export const EXTRA_STEPS = [
  "spy", "spyPick", "spyBrowse", "spyProperties", "spyLocators", "spyDefinitions", "pagesFlows", "test",
] as const;
export type ExtraStep = (typeof EXTRA_STEPS)[number];
export type SpyTourTarget = "pick" | "tree-pane" | "details" | "locator-panel" | "definitions-group";

export type TourStep = SetupStep | "complete" | ExtraStep;

export const TOUR_ACTIONS = [
  "back",
  "next",
  "close",
  "disable",
  "skip",
  "pickInterpreter",
  "installPackage",
  "recheck",
  "showDetails",
  "initProject",
  "pickApp",
  "confirmMode",
  "changeMode",
  "launch",
  "continueExtras",
  "finish",
  "openTesting",
  "openSpy",
] as const;
export type TourAction = (typeof TOUR_ACTIONS)[number];

/** A part of the sidebar the tour can point at. */
export type TourArea = "interpreter" | "package" | "app" | "mode" | "launch" | "spy" | "project" | "machine";

export interface TourButton {
  id: TourAction;
  label: string;
  primary?: boolean;
  disabled?: boolean;
  busy?: boolean;
}

export interface TourView {
  step: TourStep;
  /** `setup` is the first run, `repair` is a step that stopped working, `extras` is what comes after. */
  phase: "setup" | "repair" | "extras";
  kind: "todo" | "attention" | "done";
  /** "Step 2 of 7" */
  progress?: { index: number; total: number };
  title: string;
  text: string;
  /** What the check found, such as the path of the interpreter or the name of the failed check. */
  detail?: string;
  /** The areas that stay lit; everything else is dulled. */
  lit: TourArea[];
  /** The whole Test Target panel is the subject, so nothing in it is lit. */
  panel: boolean;
  buttons: TourButton[];
  canBack: boolean;
  canNext: boolean;
  spyTarget?: SpyTourTarget;
}

export interface TourContext {
  health: Health;
  views: Record<StepId, StepView>;
  /** The user has confirmed or changed how the app is launched. */
  modeConfirmed: boolean;
  /** The first setup was finished or closed; only steps that stop working bring the guide back. */
  completed: boolean;
  /** Where the extras are, once the user chose to continue to them. */
  extra?: ExtraStep;
  /** A step the user went back to; ignored once setup has moved to or past it. */
  cursor?: SetupStep;
  closed: boolean;
  installing: boolean;
  /** `attach` never starts the application itself. */
  launchMode: string;
  pythonName?: string;
  /** Why the package could not be installed, from the last attempt. */
  installError?: string;
}

const stateOf = (ctx: TourContext, step: SetupStep): StepView =>
  step === "mode" ? (ctx.modeConfirmed ? "ok" : "todo") : ctx.views[step];

/** The first step not done; in repair only a step that stopped working counts. */
export function firstOpenStep(ctx: TourContext): SetupStep | undefined {
  return ctx.completed
    ? SETUP_STEPS.find((step) => step !== "mode" && stateOf(ctx, step) === "attention")
    : SETUP_STEPS.find((step) => stateOf(ctx, step) !== "ok");
}

/** Whether there is something to show, even if the guide is closed right now. */
export function hasWork(ctx: TourContext): boolean {
  return !!ctx.extra || !ctx.completed || !!firstOpenStep(ctx);
}

export function planTour(ctx: TourContext): TourView | undefined {
  if (ctx.closed) return undefined;
  if (ctx.extra) return extraView(ctx.extra);
  const open = firstOpenStep(ctx);
  if (ctx.completed && !open) return undefined;
  const total = SETUP_STEPS.length;
  // With nothing left open the "all done" card comes after the last step.
  const openIndex = open ? SETUP_STEPS.indexOf(open) : total;
  const viewed =
    !ctx.completed && ctx.cursor && SETUP_STEPS.indexOf(ctx.cursor) < openIndex ? ctx.cursor : undefined;
  if (!open && !viewed) return completeView();
  const step = viewed ?? open!;
  const view = stepView(ctx, step, viewed ? "ok" : stateOf(ctx, step));
  const index = SETUP_STEPS.indexOf(step);
  return {
    ...view,
    phase: ctx.completed ? "repair" : "setup",
    progress: ctx.completed ? undefined : { index: index + 1, total },
    canBack: !ctx.completed && index > 0,
    canNext: !!viewed,
  };
}

type StepContent = Omit<TourView, "phase" | "progress" | "canBack" | "canNext">;

function stepView(ctx: TourContext, step: SetupStep, state: StepView): StepContent {
  const kind: TourView["kind"] = state === "ok"
    ? "done"
    : step === "package" && ctx.installError && !ctx.installing ? "attention" : state;
  const h = ctx.health;
  const make = (view: Omit<StepContent, "step" | "kind">): StepContent => ({ step, kind, ...view });
  const needs = kind === "attention";
  switch (step) {
    case "interpreter":
      return make({
        title: needs ? "The Python interpreter needs attention" : kind === "done" ? "Python interpreter chosen" : "Choose a Python interpreter",
        text: needs
          ? "The interpreter WinTestKit was using is gone or no longer selected. Choose one again."
          : kind === "done"
            ? "Tests run with this interpreter. Click it any time to change it."
            : "WinTestKit runs your tests with a Python interpreter. Click the interpreter tile to choose one.",
        detail: h.interpreter.detail,
        lit: ["interpreter"],
        panel: false,
        buttons: [],
      });
    case "package":
      return make({
        title: needs ? "WinTestKit needs attention" : kind === "done" ? "WinTestKit is installed" : "Install WinTestKit",
        text:
          kind === "done"
            ? "The package is installed in this interpreter."
            : ctx.installing
              ? "WinTestKit is being installed. Follow progress in the highlighted package strip above."
              : ctx.installError
                ? "Installation failed. Click Try again in the highlighted package strip above to retry."
                : `${ctx.pythonName ?? "This interpreter"} does not have WinTestKit yet. Click Install in the highlighted package strip above.`,
        detail: ctx.installError,
        lit: ["package"],
        panel: false,
        buttons: [],
      });
    case "machine":
      return make({
        title: needs ? "This machine can't run UI tests" : kind === "done" ? "This machine is capable of running this test stack and installs are clean" : "Checking this machine",
        text: needs
          ? "An environment check failed. Run WinTestKit: Check Environment (doctor) from the Command Palette to investigate and fix it."
          : kind === "done"
            ? "Every environment check passed."
            : "WinTestKit needs an unlocked, interactive Windows desktop.",
        detail: h.machine.detail,
        lit: ["machine"],
        panel: false,
        buttons: [],
      });
    case "project":
      return make({
        title: needs ? "The WinTestKit project needs attention" : kind === "done" ? "Project created" : "Create the test project",
        text: needs
          ? "The WinTestKit project is missing. Click Initialize project in Test Target to create its settings and starter files."
          : kind === "done"
            ? "This folder is a WinTestKit project."
            : "Click Initialize project in Test Target. This adds pages, flows and a smoke test, and never overwrites a file.",
        detail: h.project.detail,
        lit: ["project"],
        panel: false,
        buttons: [],
      });
    case "app":
      return make({
        title: needs ? "The application needs attention" : kind === "done" ? "Application chosen" : "Choose the application",
        text: needs
          ? "The application chosen for this project is missing or no longer set. Choose it again."
          : kind === "done"
            ? "This is the application your tests drive. Click it any time to change it."
            : "Pick the application to test. Click the application tile.",
        detail: h.app.detail,
        lit: ["app"],
        panel: false,
        buttons: [],
      });
    case "mode":
      return make({
        title: kind === "done" ? "Launch mode chosen" : "How should the app start?",
        text:
          ctx.launchMode === "attach"
            ? "Attach uses an app you started yourself and never starts or closes it. Click the launch mode tile and select a mode, even if you keep the current one."
            : "Launch for tests starts a fresh copy for every test and closes it afterwards. Click the launch mode tile and select a mode, even if you keep the current one.",
        lit: ["mode"],
        panel: false,
        buttons: [],
      });
    case "launch":
      return make({
        title: needs ? "The application can't be inspected" : kind === "done" ? "The application is running" : "Start the application",
        text: needs
          ? "The application runs with higher privileges than VS Code, so Windows blocks UI Automation. Run VS Code as administrator, or start the application normally."
          : kind === "done"
            ? "WinTestKit can see the application."
            : ctx.launchMode === "attach"
              ? "Start your application. WinTestKit will notice it."
              : "Click Launch in Test Target so WinTestKit can see the application.",
        detail: h.launch.detail,
        lit: ["launch"],
        panel: false,
        buttons: [],
      });
  }
}

function completeView(): TourView {
  return {
    step: "complete",
    phase: "setup",
    kind: "done",
    title: "You're set up",
    text: "WinTestKit is ready. Continue to a few extra features, or close this introduction.",
    lit: [],
    panel: true,
    buttons: [
      { id: "continueExtras", label: "Continue to extra features", primary: true },
      { id: "close", label: "Close introduction" },
    ],
    canBack: true,
    canNext: false,
  };
}

function extraView(extra: ExtraStep): TourView {
  const index = EXTRA_STEPS.indexOf(extra);
  const content: Record<ExtraStep, { title: string; text: string; spyTarget?: SpyTourTarget }> = {
    spy: {
      title: "Meet WinTestKit Spy",
      text: "This bottom panel is your live UI Automation workbench. The object browser on the left explores desktop windows and controls; the inspector on the right explains the selected object and helps turn it into reusable test code. You can try the real controls as you follow this optional tutorial.",
    },
    spyPick: {
      title: "Pick a control from the application",
      text: "Click Pick element, then hold Ctrl and click a control in your application. Spy selects it in the tree, inspects its properties and suggests a locator. Press Esc to stop picking. Picking is useful when you can see a control but do not know where it lives in the object tree.",
      spyTarget: "pick",
    },
    spyBrowse: {
      title: "Explore the object browser",
      text: "Expand windows and controls on the left, or use the search field to filter loaded objects. Refresh objects reloads the tree and Collapse all folds it. The scope button switches between all desktop windows and only your selected app. Select an object to inspect it; the pin button can bring its window to the front.",
      spyTarget: "tree-pane",
    },
    spyProperties: {
      title: "Understand the selected object",
      text: "The inspector groups identity, state, geometry and automation information so you can understand a control before writing a test. Highlight outlines the selected object on screen. Expand All properties and click Load all properties when you need the complete property list and supported patterns. Select or pick an object first if this area is empty.",
      spyTarget: "details",
    },
    spyLocators: {
      title: "Turn controls into reusable locators",
      text: "After you select or pick a control, Suggested locator shows Python code and whether it uniquely identifies that control. Copy locator copies the code. Add to page inserts it into an existing or new page, adds imports and leaves the change unsaved for review. A scoped locator can reuse a container to distinguish similar controls.",
      spyTarget: "locator-panel",
    },
    spyDefinitions: {
      title: "Find controls already defined in pages",
      text: "Defined in pages links the selected control to matching definitions in your page files. Open a match to jump to its Python definition instead of creating a duplicate. The object tree also marks controls that are already defined, and those markers refresh when you save a page. Select an object to see its matches.",
      spyTarget: "definitions-group",
    },
    pagesFlows: {
      title: "Organize pages and reusable flows",
      text: "Back in the WinTestKit sidebar, Page Tree organizes your page classes and their controls; click an entry to open its definition. Flows lists reusable Python workflows. Eligible flows can run directly against the application. Keep locators in pages and multi-step interactions in flows so tests stay readable. The sidebar remains usable during this tutorial.",
    },
    test: {
      title: "Run tests and inspect the result",
      text: "Click Finish when you are ready, then open Testing in the Activity Bar and use Run Test beside the smoke test. Testing runs and debugs your tests; Test Target shows the latest result and its report link. Return to the WinTestKit sidebar after a run to inspect failures and review the report. Finishing this tutorial does not change your application or project.",
    },
  };
  return {
    ...content[extra],
    step: extra,
    phase: "extras",
    kind: "todo",
    progress: { index: index + 1, total: EXTRA_STEPS.length },
    lit: ["spy"],
    panel: false,
    buttons: index === EXTRA_STEPS.length - 1
      ? [{ id: "finish", label: "Finish", primary: true }]
      : [{ id: "next", label: "Next", primary: true }],
    canBack: true,
    canNext: false,
  };
}
