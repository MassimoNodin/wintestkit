import { describe, expect, it } from "vitest";
import {
  appResult,
  blockingStep,
  gatherHealth,
  launchResult,
  machineResult,
  parseDoctor,
  STEP_IDS,
  type DoctorCheck,
  type HealthProbes,
} from "../../src/setup/health";
import { SetupTracker } from "../../src/setup/tracker";

const check = (id: string, status: DoctorCheck["status"], detail = "detail", hint?: string): DoctorCheck => ({
  id,
  title: id,
  status,
  detail,
  ...(hint ? { hint } : {}),
});

const probes = (overrides: Partial<HealthProbes> = {}): HealthProbes => ({
  interpreter: async () => "C:/py/python.exe",
  interpreterExists: () => true,
  packageInfo: async () => ({ installed: true, version: "0.1.1" }),
  doctor: async () => [check("platform", "ok"), check("uia", "ok")],
  project: async () => ({ name: "demo", config: { "app.path": "C:/Apps/Demo.exe" } }),
  appRunning: () => true,
  ...overrides,
});

describe("doctor output", () => {
  it("reads the checks even though doctor exits non-zero", () => {
    expect(parseDoctor(JSON.stringify([check("uia", "fail")]))).toEqual([check("uia", "fail")]);
    expect(parseDoctor("not json")).toBeUndefined();
    expect(parseDoctor('{"id":"x"}')).toBeUndefined();
    expect(parseDoctor(JSON.stringify([{ nope: 1 }, check("uia", "ok")]))).toEqual([check("uia", "ok")]);
  });
  it("breaks the machine step on a failed environment check, with its hint", () => {
    expect(machineResult([check("platform", "ok"), check("dpi", "fail")]).state).toBe("ok");
    const result = machineResult([check("desktop_unlocked", "fail", "the desktop is locked", "Unlock it")]);
    expect(result.state).toBe("broken");
    expect(result.detail).toContain("the desktop is locked");
    expect(result.detail).toContain("Unlock it");
  });
  it("needs a chosen application, and a file that exists when it is one", () => {
    expect(appResult({}, []).state).toBe("pending");
    expect(appResult({ "app.path": "  " }, []).state).toBe("pending");
    expect(appResult({ "app.process": "calc" }, []).state).toBe("ok");
    expect(appResult({ "app.path": "C:/x.exe" }, [check("app_path", "fail", "no such file")])).toMatchObject({
      state: "broken",
    });
  });
  it("treats the legacy starter path as unconfigured, not broken", () => {
    for (const file of ["C:/path/to/YourApp.exe", "C:\\path\\to\\YourApp.exe"]) {
      expect(appResult({ "app.path": file }, [check("app_path", "fail")])).toMatchObject({ state: "pending" });
    }
  });
  it("calls an elevated application broken, and a stopped one merely pending", () => {
    expect(launchResult(true, [check("elevation", "fail", "elevated")]).state).toBe("broken");
    expect(launchResult(true, [check("elevation", "ok")]).state).toBe("ok");
    expect(launchResult(false, [check("elevation", "skip")]).state).toBe("pending");
  });
});

describe("gathering health", () => {
  it("is all ok when everything works, and knows the installed version", async () => {
    const health = await gatherHealth(probes());
    expect(Object.keys(health)).toEqual([...STEP_IDS]);
    expect(Object.values(health).map((result) => result.state)).toEqual(Array(STEP_IDS.length).fill("ok"));
    expect(health.package.version).toBe("0.1.1");
  });
  it("waits on earlier steps instead of failing the later ones", async () => {
    const health = await gatherHealth(probes({ interpreter: async () => undefined, project: async () => undefined }));
    expect(health.interpreter.state).toBe("pending");
    expect(health.package.detail).toContain("interpreter");
    expect(health.machine.detail).toContain("package");
    expect(health.app.detail).toContain("project");
    expect(health.launch.state).toBe("pending");
  });
  it("treats an interpreter that was deleted as not selected", async () => {
    const health = await gatherHealth(probes({ interpreterExists: () => false }));
    expect(health.interpreter.detail).toContain("no longer exists");
    expect(health.package.state).toBe("pending");
  });
  it("reports a missing package and skips the environment check", async () => {
    let ran = false;
    const health = await gatherHealth(
      probes({
        packageInfo: async () => ({ installed: false }),
        doctor: async () => {
          ran = true;
          return [];
        },
      }),
    );
    expect(health.package.state).toBe("pending");
    expect(health.machine.state).toBe("pending");
    expect(ran).toBe(false);
  });
});

describe("blocking steps", () => {
  it("blocks on the first required step that is not done, in setup order", async () => {
    expect(blockingStep(await gatherHealth(probes()))).toBeUndefined();
    expect(blockingStep(await gatherHealth(probes({ interpreter: async () => undefined })))).toBe("interpreter");
    expect(blockingStep(await gatherHealth(probes({ packageInfo: async () => ({ installed: false }) })))).toBe("package");
    expect(
      blockingStep(await gatherHealth(probes({ doctor: async () => [check("desktop_unlocked", "fail")] }))),
    ).toBe("machine");
    expect(blockingStep(await gatherHealth(probes({ project: async () => undefined })))).toBe("project");
  });
  it("does not block on an environment check that could not run", async () => {
    expect(blockingStep(await gatherHealth(probes({ doctor: async () => undefined })))).toBeUndefined();
  });
  it("does not block on choosing or starting the application", async () => {
    const health = await gatherHealth(probes({ project: async () => ({ name: "d", config: {} }), appRunning: () => false }));
    expect(health.app.state).toBe("pending");
    expect(health.launch.state).toBe("pending");
    expect(blockingStep(health)).toBeUndefined();
  });
});

describe("setup tracker", () => {
  const healthy = () => gatherHealth(probes());
  it("is quiet while everything is fine", async () => {
    const tracker = new SetupTracker();
    const first = tracker.update(await healthy());
    expect(first.announce).toBeUndefined();
    expect(first.passedChanged).toBe(true);
    expect(tracker.update(await healthy()).passedChanged).toBe(false);
  });
  it("announces a step that stopped working once, then again after it recovers", async () => {
    const tracker = new SetupTracker();
    tracker.update(await healthy());
    const gone = await gatherHealth(probes({ packageInfo: async () => ({ installed: false }) }));
    expect(tracker.update(gone).announce).toMatchObject({ step: "package" });
    expect(tracker.update(gone).announce).toBeUndefined();
    tracker.update(await healthy());
    expect(tracker.update(gone).announce).toMatchObject({ step: "package" });
  });
  it("reports only the first failing step, then the next once it is fixed", async () => {
    const tracker = new SetupTracker();
    tracker.update(await healthy());
    const noInterpreter = await gatherHealth(probes({ interpreter: async () => undefined }));
    expect(tracker.update(noInterpreter).announce).toMatchObject({ step: "interpreter" });
    const noPackage = await gatherHealth(probes({ packageInfo: async () => ({ installed: false }) }));
    expect(tracker.update(noPackage).announce).toMatchObject({ step: "package" });
  });
  it("asks about a missing package in a WinTestKit project that never worked, but not elsewhere", async () => {
    const noPackage = (project: HealthProbes["project"]) =>
      gatherHealth(probes({ packageInfo: async () => ({ installed: false }), project }));
    expect(new SetupTracker().update(await noPackage(async () => ({ name: "d", config: {} }))).announce).toMatchObject({
      step: "package",
    });
    expect(new SetupTracker().update(await noPackage(async () => undefined)).announce).toBeUndefined();
  });
  it("does not mention a stopped application, but does mention an elevated one", async () => {
    const tracker = new SetupTracker();
    tracker.update(await healthy());
    expect(tracker.update(await gatherHealth(probes({ appRunning: () => false }))).announce).toBeUndefined();
    const elevated = await gatherHealth(
      probes({ doctor: async () => [check("elevation", "fail", "pid 5 is elevated")] }),
    );
    expect(tracker.update(elevated).announce).toMatchObject({ step: "launch" });
  });
  it("says so when the application disappears", async () => {
    const tracker = new SetupTracker();
    tracker.update(await healthy());
    const noApp = await gatherHealth(probes({ project: async () => ({ name: "d", config: {} }) }));
    expect(tracker.update(noApp).announce).toMatchObject({ step: "app" });
  });
  it("shows steps as done, to do, or needing attention", async () => {
    const tracker = new SetupTracker();
    const fresh = await gatherHealth(probes({ interpreter: async () => undefined, project: async () => undefined }));
    tracker.update(fresh);
    // Nothing has worked yet and this is not a WinTestKit project: every unfinished step is simply to do.
    expect(tracker.views(fresh)).toMatchObject({ interpreter: "todo", package: "todo", project: "todo", launch: "todo" });
    const working = await healthy();
    tracker.update(working);
    expect(Object.values(tracker.views(working))).toEqual(Array(STEP_IDS.length).fill("ok"));
    // Once they worked, a step that stops is flagged; a stopped app is just to do.
    const later = await gatherHealth(probes({ interpreter: async () => undefined, appRunning: () => false }));
    tracker.update(later);
    expect(tracker.views(later)).toMatchObject({ interpreter: "attention", launch: "todo" });
    const elevated = await gatherHealth(probes({ doctor: async () => [check("elevation", "fail", "elevated")] }));
    expect(tracker.views(elevated).launch).toBe("attention");
  });
  it("remembers what passed across sessions", async () => {
    const first = new SetupTracker();
    first.update(await healthy());
    const restored = new SetupTracker(first.passedSteps());
    const noProject = await gatherHealth(probes({ project: async () => undefined }));
    expect(restored.update(noProject).announce).toMatchObject({ step: "project" });
    expect(new SetupTracker().update(noProject).announce).toBeUndefined();
  });
});
