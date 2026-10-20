import { packageCompatibility } from "../compatibility";

/** The setup steps that can be checked, in the order the setup guide shows them. */
export const STEP_IDS = [
  "interpreter",
  "package",
  "machine",
  "project",
  "app",
  "launch",
] as const;
export type StepId = (typeof STEP_IDS)[number];

/** `ok` is done, `pending` is not done yet, `broken` is wrong right now. */
export type StepState = "ok" | "pending" | "broken";
export interface StepResult {
  state: StepState;
  detail: string;
  /** The installed wintestkit version, on the package step. */
  version?: string;
}
export type Health = Record<StepId, StepResult>;

/** How the setup guide presents a step: done, still to do, or something that worked and now needs attention. */
export type StepView = "ok" | "todo" | "attention";

/**
 * When a step that is not ok is worth interrupting the user for:
 * `whenProject` once the folder is a WinTestKit project (or it worked before),
 * `regress` only after it worked before, `broken` only when it is actively wrong, `never` not at all.
 */
export type Notify = "whenProject" | "regress" | "broken" | "never";

export const STEPS: Record<StepId, { title: string; notify: Notify }> = {
  interpreter: { title: "Python interpreter", notify: "whenProject" },
  package: { title: "The wintestkit package", notify: "whenProject" },
  machine: { title: "This machine", notify: "broken" },
  project: { title: "The WinTestKit project", notify: "regress" },
  app: { title: "The application to test", notify: "regress" },
  launch: { title: "Launching the application", notify: "broken" },
};

/**
 * The steps WinTestKit cannot work without. While one of them is not ok and the setup guide is closed,
 * the sidebar is just a button that reopens it. Choosing the application and starting it are part of
 * using WinTestKit, not of setting it up, so those are not here.
 */
export const BLOCKING_STEPS: readonly StepId[] = ["interpreter", "package", "machine", "project"];

export function blockingStep(health: Health): StepId | undefined {
  // An environment check that could not run says nothing against the machine, so only a failure counts.
  return BLOCKING_STEPS.find((step) =>
    step === "machine" ? health[step].state === "broken" : health[step].state !== "ok",
  );
}

export interface DoctorCheck {
  id: string;
  title: string;
  status: "ok" | "warn" | "fail" | "skip";
  detail: string;
  hint?: string;
}

/** The doctor checks that say whether this machine and session can run UI tests at all. */
const MACHINE_CHECKS = new Set([
  "platform",
  "python",
  "interactive_session",
  "desktop_unlocked",
  "remote_session",
  "uia",
]);

const ok = (detail: string): StepResult => ({ state: "ok", detail });
const pending = (detail: string): StepResult => ({ state: "pending", detail });
const broken = (detail: string): StepResult => ({ state: "broken", detail });

/** `wtk doctor --json` prints the checks even when it exits non-zero, so read stdout either way. */
export function parseDoctor(stdout: string): DoctorCheck[] | undefined {
  try {
    const value: unknown = JSON.parse(stdout);
    if (!Array.isArray(value)) return undefined;
    return value.filter(
      (entry): entry is DoctorCheck =>
        !!entry && typeof entry.id === "string" && typeof entry.status === "string",
    );
  } catch {
    return undefined;
  }
}

function failure(check: DoctorCheck): string {
  return check.hint
    ? `${check.title}: ${check.detail}. ${check.hint}`
    : `${check.title}: ${check.detail}`;
}

export function machineResult(checks: readonly DoctorCheck[]): StepResult {
  const failed = checks.find((check) => MACHINE_CHECKS.has(check.id) && check.status === "fail");
  return failed ? broken(failure(failed)) : ok("This machine can run UI tests");
}

/** The application is chosen and, when it is a file, that file exists. */
export function isStarterAppPath(value: unknown): boolean {
  return typeof value === "string" && value.trim().replace(/\\/g, "/").toLowerCase() === "c:/path/to/yourapp.exe";
}

export function appResult(
  config: Record<string, unknown> | undefined,
  checks: readonly DoctorCheck[] | undefined,
): StepResult {
  const text = (key: string) => {
    const value = config?.[key];
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
  };
  const file = text("app.path");
  const target = (isStarterAppPath(file) ? undefined : file) ?? text("app.process");
  if (!target) return pending("No application is chosen yet");
  const missing = checks?.find((check) => check.id === "app_path" && check.status === "fail");
  return missing ? broken(failure(missing)) : ok(target);
}

/** Launching needs the application running, and running at the same privilege level as VS Code. */
export function launchResult(
  running: boolean,
  checks: readonly DoctorCheck[] | undefined,
): StepResult {
  const elevation = checks?.find((check) => check.id === "elevation" && check.status === "fail");
  if (elevation) return broken(failure(elevation));
  return running ? ok("The application is running") : pending("The application is not running");
}

export interface HealthProbes {
  /** The interpreter VS Code would use for the project, if one is selected. */
  interpreter(): Promise<string | undefined>;
  interpreterExists(python: string): boolean;
  packageInfo(python: string): Promise<{ installed: boolean; version?: string }>;
  doctor(python: string): Promise<DoctorCheck[] | undefined>;
  /** Undefined when there is no WinTestKit project in the folder. */
  project(): Promise<{ name: string; config: Record<string, unknown> | undefined } | undefined>;
  appRunning(): boolean;
}

/** Runs every check once. A step whose earlier steps are not done says so instead of failing. */
export async function gatherHealth(probes: HealthProbes): Promise<Health> {
  const python = await probes.interpreter();
  const interpreter: StepResult = !python
    ? pending("No Python interpreter is selected")
    : probes.interpreterExists(python)
      ? ok(python)
      : pending(`The selected interpreter no longer exists: ${python}`);
  const usable = interpreter.state === "ok" ? python : undefined;
  const info = usable ? await probes.packageInfo(usable) : undefined;
  const issue = info?.installed ? packageCompatibility(info.version) : undefined;
  const packageResult: StepResult = !usable
    ? pending("Select a Python interpreter first")
    : info?.installed
      ? issue
        ? { state: "broken", detail: issue.message + " Selected interpreter: " + usable, version: info.version }
        : { ...ok(`wintestkit ${info.version ?? ""}`.trim()), version: info.version }
      : pending(`The wintestkit package is not installed in ${usable}`);
  const project = await probes.project();
  const checks = info?.installed && !issue && usable ? await probes.doctor(usable) : undefined;
  const waiting = pending("Install a compatible wintestkit package first");
  const needsProject = pending("Initialize a project first");
  return {
    interpreter,
    package: packageResult,
    machine: !info?.installed || issue
      ? waiting
      : checks
        ? machineResult(checks)
        : pending("The environment check could not run"),
    project: project ? ok(project.name) : pending("No WinTestKit project in this folder"),
    app: project ? appResult(project.config, checks) : needsProject,
    launch: project ? launchResult(probes.appRunning(), checks) : needsProject,
  };
}
