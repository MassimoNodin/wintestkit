import type { CollectedTest, RunEvent } from "../protocol/generated";

export type TestEnd = Extract<RunEvent, { event: "test_end" }>;
export type RunAction =
  | { kind: "createChild"; id: string; parent?: string; test?: CollectedTest }
  | { kind: "enqueue" | "started" | "skipped"; id: string }
  | {
      kind: "passed" | "failed" | "errored";
      id: string;
      duration?: number;
      end?: TestEnd;
      message?: string;
    }
  | { kind: "output"; id?: string; text: string }
  | { kind: "report"; path?: string; failed: number };

export function terminalText(text: string): string {
  return text.replace(/\r?\n/g, "\r\n");
}
export class EventMapper {
  private readonly pending = new Set<string>();
  private readonly known = new Set<string>();
  ended = false;
  constructor(ids: string[] = []) {
    ids.forEach((id) => {
      this.pending.add(id);
      this.known.add(id);
    });
  }
  private ensure(id: string, actions: RunAction[], test?: CollectedTest): void {
    if (this.known.has(id)) return;
    const parent = id.includes("[")
      ? id.slice(0, id.indexOf("["))
      : (test?.parent ?? undefined);
    actions.push({ kind: "createChild", id, parent, test });
    if (parent) this.pending.delete(parent);
    this.known.add(id);
  }
  consume(event: RunEvent): RunAction[] {
    if (this.ended) return [];
    const actions: RunAction[] = [];
    switch (event.event) {
      case "collected":
        for (const test of event.tests) {
          this.ensure(test.id, actions, test);
          this.pending.add(test.id);
          actions.push({ kind: "enqueue", id: test.id });
        }
        for (const error of event.errors)
          actions.push({
            kind: "errored",
            id: error.file,
            message: error.message,
          });
        break;
      case "test_start":
        this.ensure(event.id, actions);
        this.pending.add(event.id);
        actions.push({ kind: "started", id: event.id });
        break;
      case "step":
        actions.push({
          kind: "output",
          id: event.id,
          text:
            "  \u25b8 " +
            event.step.action +
            " " +
            event.step.target +
            " (" +
            event.step.duration.toFixed(2) +
            "s)\r\n",
        });
        break;
      case "test_output":
        actions.push({
          kind: "output",
          id: event.id,
          text: terminalText(event.text),
        });
        break;
      case "test_end":
        this.ensure(event.id, actions);
        this.pending.delete(event.id);
        actions.push({
          kind: event.outcome === "error" ? "errored" : event.outcome,
          id: event.id,
          duration: event.duration * 1000,
          end: event,
        });
        break;
      case "session_end":
        this.ended = true;
        for (const id of this.pending)
          actions.push({
            kind:
              event.exitCode === 0 || event.exitCode === 1
                ? "skipped"
                : "errored",
            id,
            message:
              "Test session ended before this test completed (code " +
              event.exitCode +
              "). See output.",
          });
        this.pending.clear();
        const failed = event.summary.failed + event.summary.errors;
        if (event.reportPath || failed)
          actions.push({ kind: "report", path: event.reportPath, failed });
        break;
    }
    return actions;
  }
  finish(code: number | null, cancelled = false): RunAction[] {
    if (this.ended) return [];
    this.ended = true;
    const actions: RunAction[] = [...this.pending].map((id) =>
      cancelled
        ? { kind: "skipped", id }
        : {
            kind: "errored",
            id,
            message:
              "Test process exited unexpectedly (code " +
              code +
              "). See output.",
          },
    );
    this.pending.clear();
    return actions;
  }
}
