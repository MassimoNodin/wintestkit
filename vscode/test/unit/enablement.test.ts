import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  execute: vi.fn(async () => undefined),
}));
vi.mock("vscode", () => {
  class EventEmitter {
    private listeners = new Set<(value: unknown) => void>();
    event = (listener: (value: unknown) => void) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
    fire(value: unknown) {
      this.listeners.forEach((listener) => listener(value));
    }
    dispose() {}
  }
  return { EventEmitter, commands: { executeCommand: mocks.execute } };
});
import { Enablement } from "../../src/enablement";

const memento = (initial?: boolean) => {
  const values = new Map<string, unknown>(initial === undefined ? [] : [["wintestkit.enabled", initial]]);
  return {
    get: <T>(key: string, fallback?: T) => (values.has(key) ? (values.get(key) as T) : fallback),
    update: async (key: string, value: unknown) => void values.set(key, value),
  };
};

describe("enabling WinTestKit for a workspace", () => {
  beforeEach(() => vi.clearAllMocks());
  it("is off until the user turns it on, and publishes that as a context key", async () => {
    const enablement = new Enablement(memento() as never);
    expect(enablement.enabled).toBe(false);
    expect(mocks.execute).toHaveBeenCalledWith("setContext", "wintestkit.enabled", false);
    const changed = vi.fn();
    enablement.onDidChange(changed);
    await enablement.set(true);
    expect(enablement.enabled).toBe(true);
    expect(mocks.execute).toHaveBeenLastCalledWith("setContext", "wintestkit.enabled", true);
    expect(changed).toHaveBeenCalledWith(true);
    await enablement.set(true);
    expect(changed).toHaveBeenCalledOnce();
    await enablement.set(false);
    expect(changed).toHaveBeenLastCalledWith(false);
  });
  it("remembers the choice for the workspace", () => {
    expect(new Enablement(memento(true) as never).enabled).toBe(true);
  });
});
