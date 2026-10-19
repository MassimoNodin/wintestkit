import { describe, expect, it } from "vitest";
import { gatherHealth, type HealthProbes, type StepId } from "../../src/setup/health";
import {
  firstOpenStep,
  hasWork,
  planTour,
  SETUP_STEPS,
  EXTRA_STEPS,
  TOUR_ACTIONS,
  type TourContext,
} from "../../src/setup/tour";
import { SetupTracker } from "../../src/setup/tracker";

const probes = (overrides: Partial<HealthProbes> = {}): HealthProbes => ({
  interpreter: async () => "C:/py/python.exe",
  interpreterExists: () => true,
  packageInfo: async () => ({ installed: true, version: "0.1.1" }),
  doctor: async () => [],
  project: async () => ({ name: "demo", config: { "app.path": "C:/Apps/Demo.exe" } }),
  appRunning: () => true,
  ...overrides,
});

/** A tour context from the same checks the monitor runs. */
async function context(
  overrides: Partial<HealthProbes> = {},
  extra: Partial<TourContext> = {},
  passed: StepId[] = [],
): Promise<TourContext> {
  const health = await gatherHealth(probes(overrides));
  const tracker = new SetupTracker(passed);
  tracker.update(health);
  return {
    health,
    views: tracker.views(health),
    modeConfirmed: false,
    completed: false,
    closed: false,
    installing: false,
    launchMode: "per-test",
    pythonName: ".venv",
    ...extra,
  };
}
const nothing: Partial<HealthProbes> = {
  interpreter: async () => undefined,
  project: async () => undefined,
};

describe("the guided setup tour", () => {
  it("describes a clean machine check without extra action buttons", async () => {
    const tour = planTour(await context({}, { cursor: "machine" }));
    expect(tour).toMatchObject({
      step: "machine",
      title: "This machine is capable of running this test stack and installs are clean",
      buttons: [],
    });
  });

  it("starts at the interpreter, lighting its tile", async () => {
    const tour = planTour(await context(nothing));
    expect(tour).toMatchObject({
      step: "interpreter",
      phase: "setup",
      kind: "todo",
      progress: { index: 1, total: 7 },
      lit: ["interpreter"],
      panel: false,
      canBack: false,
      canNext: false,
    });
    expect(tour?.buttons).toEqual([]);
  });

  it("lights only the package strip and directs installation through its button", async () => {
    const missing = { packageInfo: async () => ({ installed: false }) };
    const tour = planTour(await context({ ...missing, project: async () => undefined }));
    expect(tour).toMatchObject({ step: "package", lit: ["package"], canBack: true });
    expect(tour?.text).toContain(".venv");
    expect(tour?.buttons).toEqual([]);
    expect(tour?.detail).toBeUndefined();
    expect(tour?.text).toContain("Click Install in the highlighted package strip above");
    const installing = planTour(await context({ ...missing, project: async () => undefined }, { installing: true }));
    expect(installing?.buttons).toEqual([]);
    expect(installing?.text).toContain("being installed");
    const failed = planTour(
      await context({ ...missing, project: async () => undefined }, { installError: "no network" }),
    );
    expect(failed?.detail).toBe("no network");
    expect(failed?.kind).toBe("attention");
    expect(failed?.buttons).toEqual([]);
    expect(failed?.text).toContain("Click Try again");
  });

  it("points to the real machine and project controls without duplicate actions", async () => {
    const machine = planTour(
      await context({ doctor: async () => [{ id: "desktop_unlocked", title: "x", status: "fail", detail: "locked" }] }),
    );
    expect(machine).toMatchObject({ step: "machine", panel: false, lit: ["machine"], kind: "attention" });
    expect(machine?.detail).toContain("locked");
    expect(machine?.buttons).toEqual([]);
    const project = planTour(await context({ project: async () => undefined }));
    expect(project).toMatchObject({ step: "project", panel: false, lit: ["project"] });
    expect(project?.buttons).toEqual([]);
  });

  it("asks for the application, then the launch mode on its own, then to start it", async () => {
    const noApp = { project: async () => ({ name: "d", config: {} }) };
    expect(planTour(await context(noApp))).toMatchObject({ step: "app", lit: ["app"] });
    const mode = planTour(await context({}));
    expect(mode).toMatchObject({ step: "mode", lit: ["mode"], progress: { index: 6, total: 7 } });
    expect(mode?.buttons).toEqual([]);
    const launch = planTour(await context({ appRunning: () => false }, { modeConfirmed: true }));
    expect(launch).toMatchObject({ step: "launch", lit: ["launch"] });
    expect(launch?.buttons).toEqual([]);
    const attach = planTour(await context({ appRunning: () => false }, { modeConfirmed: true, launchMode: "attach" }));
    expect(attach?.text).toContain("Start your application");
    expect(attach?.buttons).toEqual([]);
  });

  it("ends with a card that offers the extra features or closing the introduction", async () => {
    const tour = planTour(await context({}, { modeConfirmed: true }));
    expect(tour).toMatchObject({ step: "complete", panel: true, kind: "done" });
    expect(tour?.buttons.map((button) => button.id)).toEqual(["continueExtras", "close"]);
  });

  it("introduces each main feature in the extra tutorial, ending with tests", async () => {
    const base = await context({}, { modeConfirmed: true });
    const spy = planTour({ ...base, extra: "spy" });
    expect(spy).toMatchObject({ step: "spy", phase: "extras", lit: ["spy"], progress: { index: 1, total: EXTRA_STEPS.length } });
    expect(spy?.buttons.map((button) => button.id)).toEqual(["next"]);
    expect(spy?.text).toContain("panel");
    const test = planTour({ ...base, extra: "test" });
    expect(test).toMatchObject({ step: "test", progress: { index: EXTRA_STEPS.length, total: EXTRA_STEPS.length } });
    expect(test?.buttons.map((button) => button.id)).toEqual(["finish"]);
    expect(test?.text).toContain("Return to the WinTestKit sidebar");
    for (const [index, extra] of EXTRA_STEPS.entries()) {
      const view = planTour({ ...base, extra });
      expect(view).toMatchObject({ step: extra, phase: "extras", progress: { index: index + 1, total: EXTRA_STEPS.length } });
      expect(view?.text.length).toBeGreaterThan(100);
      expect(view?.buttons.map((button) => button.id)).toEqual([extra === "test" ? "finish" : "next"]);
    }
  });

  it("lets the user go back to a finished step and forward again, never past the first open one", async () => {
    const ready = await context({ appRunning: () => false }, { modeConfirmed: true });
    const back = planTour({ ...ready, cursor: "app" });
    expect(back).toMatchObject({ step: "app", kind: "done", canNext: true, canBack: true });
    expect(back?.buttons).toEqual([]);
    // A cursor at or after the first open step is ignored: the tour follows the checks.
    expect(planTour({ ...ready, cursor: "launch" })).toMatchObject({ step: "launch", canNext: false });
    // After everything is done, going back from the final card reaches the last step.
    const complete = await context({}, { modeConfirmed: true, cursor: "launch" });
    expect(planTour(complete)).toMatchObject({ step: "launch", kind: "done", canNext: true });
  });

  it("follows the checks when the step being looked at moves on", async () => {
    const before = await context(nothing, { cursor: "interpreter" });
    expect(planTour(before)?.step).toBe("interpreter");
    const after = await context({}, { cursor: "interpreter", modeConfirmed: false });
    expect(planTour(after)?.step).toBe("interpreter");
    const fixed = await context({ appRunning: () => false }, { cursor: "interpreter", modeConfirmed: true });
    expect(planTour(fixed)).toMatchObject({ step: "interpreter", kind: "done" });
  });

  it("is hidden when closed, but there is still something to resume", async () => {
    const closed = await context(nothing, { closed: true });
    expect(planTour(closed)).toBeUndefined();
    expect(hasWork(closed)).toBe(true);
  });

  it("after setup is finished only brings itself back for a step that stopped working", async () => {
    const done = await context({ appRunning: () => false }, { completed: true, modeConfirmed: true }, [
      "interpreter", "package", "machine", "project", "app", "launch",
    ]);
    // A stopped application is normal once setup is done.
    expect(planTour(done)).toBeUndefined();
    expect(hasWork(done)).toBe(false);
    const broken = await context(
      { packageInfo: async () => ({ installed: false }) },
      { completed: true, modeConfirmed: true },
      ["interpreter", "package", "machine", "project", "app", "launch"],
    );
    const repair = planTour(broken);
    expect(repair).toMatchObject({ step: "package", phase: "repair", kind: "attention", canBack: false });
    expect(repair?.progress).toBeUndefined();
    expect(firstOpenStep(broken)).toBe("package");
  });

  it("explains an application that runs elevated", async () => {
    const tour = planTour(
      await context({ doctor: async () => [{ id: "elevation", title: "x", status: "fail", detail: "pid 5 is elevated" }] }, { modeConfirmed: true }),
    );
    expect(tour).toMatchObject({ step: "launch", kind: "attention" });
    expect(tour?.text).toContain("administrator");
  });

  it("only offers actions the sidebar accepts", async () => {
    const offered = new Set<string>();
    for (const probe of [nothing, { project: async () => undefined }, {}, { appRunning: () => false }])
      for (const extra of [{}, { modeConfirmed: true }, { installing: true }])
        for (const view of [planTour(await context(probe, extra))])
          view?.buttons.forEach((button) => offered.add(button.id));
    for (const extra of ["spy", "test"] as const)
      planTour({ ...(await context({}, { modeConfirmed: true })), extra })?.buttons.forEach((button) => offered.add(button.id));
    for (const id of offered) expect(TOUR_ACTIONS as readonly string[]).toContain(id);
    expect(SETUP_STEPS).toHaveLength(7);
  });
});
