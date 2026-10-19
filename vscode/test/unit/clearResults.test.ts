import { beforeEach, describe, expect, it, vi } from "vitest";

const commands = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  native: vi.fn<(...args: unknown[]) => Promise<void>>(async () => {}),
}));
vi.mock("vscode", () => ({
  commands: {
    registerCommand: (id: string, handler: (...args: unknown[]) => unknown) => {
      expect(commands.handlers.has(id)).toBe(false);
      commands.handlers.set(id, handler);
      return { dispose: () => commands.handlers.delete(id) };
    },
    executeCommand: (id: string, ...args: unknown[]) =>
      (commands.handlers.get(id) ?? commands.native)(...args),
  },
}));
import { CLEAR_RESULTS_COMMAND, registerClearResults } from "../../src/testing/clearResults";

beforeEach(() => { commands.handlers.clear(); commands.native.mockReset(); });

describe("native clear-results bridge", () => {
  it("snapshots before native clear and restores the wrapper for subsequent clicks", async () => {
    const order: string[] = [];
    const clear = vi.fn(async () => { order.push("cleanup"); });
    commands.native.mockImplementation(async () => { order.push("native"); });
    const registration = registerClearResults(() => { order.push("snapshot"); return clear; });
    await commands.handlers.get(CLEAR_RESULTS_COMMAND)?.("argument");
    await commands.handlers.get(CLEAR_RESULTS_COMMAND)?.();
    expect(order).toEqual(["snapshot", "native", "cleanup", "snapshot", "native", "cleanup"]);
    expect(commands.native).toHaveBeenNthCalledWith(1, "argument");
    registration.dispose();
    expect(commands.handlers.size).toBe(0);
  });

  it("does not delete reports if native clearing fails, and remains registered", async () => {
    const clear = vi.fn(async () => {});
    commands.native.mockRejectedValueOnce(new Error("native failed"));
    const registration = registerClearResults(() => clear);
    await expect(commands.handlers.get(CLEAR_RESULTS_COMMAND)?.()).rejects.toThrow("native failed");
    expect(clear).not.toHaveBeenCalled();
    expect(commands.handlers.has(CLEAR_RESULTS_COMMAND)).toBe(true);
    registration.dispose();
  });

  it("restores the wrapper if deleting a report fails", async () => {
    const registration = registerClearResults(() => async () => { throw new Error("locked"); });
    await expect(commands.handlers.get(CLEAR_RESULTS_COMMAND)?.()).rejects.toThrow("locked");
    expect(commands.handlers.has(CLEAR_RESULTS_COMMAND)).toBe(true);
    registration.dispose();
  });

  it("does not register again if the extension is disposed during clearing", async () => {
    let finish!: () => void;
    commands.native.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
    const registration = registerClearResults(() => async () => {});
    const pending = commands.handlers.get(CLEAR_RESULTS_COMMAND)?.();
    registration.dispose();
    finish();
    await pending;
    expect(commands.handlers.size).toBe(0);
  });
});
