import { readFileSync } from "node:fs";
import * as net from "node:net";
import { describe, expect, it, vi } from "vitest";
import type { RunEvent } from "../../src/protocol/generated";
import { EventMapper, terminalText } from "../../src/testing/eventMapper";
import { EventServer } from "../../src/testing/eventServer";

const events = readFileSync(
  "../python/tests/contract/fixtures/events.ndjson",
  "utf8",
)
  .trim()
  .split("\n")
  .map((line) => JSON.parse(line) as RunEvent);
describe("test event mapping", () => {
  it("replays Python events with parameterized children and millisecond durations", () => {
    const mapper = new EventMapper(["tests/test_login.py::test_sign_in"]);
    const actions = events.flatMap((event) => mapper.consume(event));
    expect(actions.map((action) => action.kind)).toEqual([
      "createChild",
      "enqueue",
      "started",
      "output",
      "output",
      "passed",
      "report",
    ]);
    expect(actions[0]).toMatchObject({
      parent: "tests/test_login.py::test_sign_in",
    });
    expect(actions.find((action) => action.kind === "passed")).toMatchObject({
      duration: 200,
    });
    expect(mapper.finish(0)).toEqual([]);
  });
  it("reports setup errors, skips cancellations and errors on unexpected exit", () => {
    const mapper = new EventMapper(["test"]);
    expect(
      mapper.consume({
        event: "test_end",
        time: 0,
        id: "test",
        outcome: "error",
        duration: 1,
        error: { type: "RuntimeError", message: "Setup failed" },
        screenshots: [],
      })[0],
    ).toMatchObject({ kind: "errored", duration: 1000 });
    expect(new EventMapper(["test"]).finish(null, true)).toEqual([
      { kind: "skipped", id: "test" },
    ]);
    expect(new EventMapper(["test"]).finish(2)[0]).toMatchObject({
      kind: "errored",
      message: "Test process exited unexpectedly (code 2). See output.",
    });
  });
  it("keeps the attach-not-running error type on the errored action", () => {
    const [action] = new EventMapper(["test"]).consume({
      event: "test_end",
      time: 0,
      id: "test",
      outcome: "error",
      duration: 0,
      message: "THE APP WAS NOT LAUNCHED",
      error: { type: "AttachNotRunningError", message: "THE APP WAS NOT LAUNCHED" },
      screenshots: [],
    });
    expect(action).toMatchObject({ kind: "errored" });
    expect(action.kind === "errored" && action.end?.error?.type).toBe("AttachNotRunningError");
  });
  it("emits last-run totals for successful runs without an HTML report", () => {
    const actions = new EventMapper().consume({
      event: "session_end", time: 1, exitCode: 0,
      summary: { total: 2, passed: 2, failed: 0, errors: 0, skipped: 0, duration: 1 },
    });
    expect(actions).toContainEqual({ kind: "report", path: undefined, failed: 0, passed: 2 });
  });
  it("normalizes newlines without doubling CRLF", () => {
    expect(terminalText("first\nsecond\r\n")).toBe("first\r\nsecond\r\n");
  });
  it("receives chunked Unicode NDJSON on a loopback ephemeral port", async () => {
    const received: RunEvent[] = [];
    const error = vi.fn();
    const listener = new EventServer((event) => received.push(event), error);
    try {
      const url = new URL(await listener.listen());
      const client = net.connect(Number(url.port), url.hostname);
      await new Promise<void>((resolve) => client.once("connect", resolve));
      const payload = Buffer.from(
        JSON.stringify({
          event: "test_output",
          time: 0,
          id: "test",
          stream: "stdout",
          text: "\u00e9",
        }) + "\n",
      );
      client.write(payload.subarray(0, payload.length - 4));
      client.end(payload.subarray(payload.length - 4));
      await listener.drain();
      expect(received).toHaveLength(1);
      expect(received[0]).toMatchObject({ text: "\u00e9" });
      expect(error).not.toHaveBeenCalled();
    } finally {
      listener.dispose();
    }
  });
});
