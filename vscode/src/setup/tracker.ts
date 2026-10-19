import { STEP_IDS, STEPS, type Health, type StepId, type StepView } from "./health";

export interface SetupProblem {
  step: StepId;
  title: string;
  detail: string;
}

/**
 * Decides which steps need attention. A step that is not ok only counts when it used to work, is
 * expected to work (the folder is a WinTestKit project), or is actively wrong. Only the first problem in
 * setup order is announced, since the steps after it usually fail because of it, and it is announced
 * once until the step works again.
 */
export class SetupTracker {
  private readonly passed: Set<StepId>;
  private readonly announced = new Set<StepId>();
  constructor(passed: Iterable<StepId> = []) {
    this.passed = new Set(passed);
  }
  passedSteps(): StepId[] {
    return [...this.passed];
  }
  /** Not ok, and either wrong right now or something that worked before (or is expected to work). */
  private isProblem(step: StepId, health: Health): boolean {
    const { state } = health[step];
    const { notify } = STEPS[step];
    if (state === "ok" || notify === "never") return false;
    if (state === "broken") return true;
    if (notify === "regress") return this.passed.has(step);
    return notify === "whenProject" && (this.passed.has(step) || health.project.state === "ok");
  }
  /** How the guide should present each step: done, still to do, or needing attention. */
  views(health: Health): Record<StepId, StepView> {
    const views = {} as Record<StepId, StepView>;
    for (const step of STEP_IDS)
      views[step] =
        health[step].state === "ok" ? "ok" : this.isProblem(step, health) ? "attention" : "todo";
    return views;
  }
  /** Returns the problem to announce now, if there is a new one. */
  update(health: Health): { announce?: SetupProblem; passedChanged: boolean } {
    let passedChanged = false;
    for (const step of STEP_IDS) {
      if (health[step].state !== "ok") continue;
      if (!this.passed.has(step)) passedChanged = true;
      this.passed.add(step);
      this.announced.delete(step);
    }
    const step = STEP_IDS.find((candidate) => this.isProblem(candidate, health));
    if (!step || this.announced.has(step)) return { passedChanged };
    this.announced.add(step);
    return {
      announce: { step, title: STEPS[step].title, detail: health[step].detail },
      passedChanged,
    };
  }
}
