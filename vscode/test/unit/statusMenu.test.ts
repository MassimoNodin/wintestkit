import { describe, expect, it, vi } from "vitest";
import { runStatusMenu, statusMenuActions } from "../../src/statusMenu";

describe("WinTestKit status menu", () => {
  it("shows state-appropriate lifecycle actions and test entry points", () => {
    const stopped = statusMenuActions(false);
    const running = statusMenuActions(true);
    expect(stopped.map((item) => item.label)).toContain("Launch App");
    expect(stopped.map((item) => item.label)).not.toContain("Close App");
    expect(running.map((item) => item.label)).toContain("Close App");
    expect(running.map((item) => item.label)).toContain("Restart App");
    for (const actions of [stopped, running]) {
      expect(actions.map((item) => item.command)).toContain("testing.runAll");
      expect(actions.map((item) => item.command)).toContain("wintestkit.openTesting");
    }
  });
  it("does not execute a command when the user dismisses the quick pick", async () => {
    const execute = vi.fn(async () => undefined);
    await runStatusMenu(statusMenuActions(false), async () => undefined, execute);
    expect(execute).not.toHaveBeenCalled();
  });
  it("executes the selected command", async () => {
    const execute = vi.fn(async () => undefined);
    await runStatusMenu(statusMenuActions(false), async (actions) => actions[1], execute);
    expect(execute).toHaveBeenCalledWith("testing.runAll");
  });
});
