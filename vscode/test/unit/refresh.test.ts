import { afterEach, describe, expect, it, vi } from "vitest";
import { LatestRefresh } from "../../src/discovery/refresh";

afterEach(() => vi.useRealTimers());
describe("latest discovery refresh", () => {
  it("debounces edits for 400 ms", async () => {
    vi.useFakeTimers();
    const load = vi.fn(async () => "latest");
    const apply = vi.fn();
    const refresh = new LatestRefresh(load, apply, vi.fn());
    refresh.schedule("project", 400);
    await vi.advanceTimersByTimeAsync(300);
    refresh.schedule("project", 400);
    await vi.advanceTimersByTimeAsync(399);
    expect(load).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(load).toHaveBeenCalledOnce();
    expect(apply).toHaveBeenCalledWith("project", "latest");
    refresh.dispose();
  });
  it("coalesces in-flight requests and discards obsolete results", async () => {
    let finish!: (value: string) => void;
    const load = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<string>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue("new");
    const apply = vi.fn();
    const refresh = new LatestRefresh<string>(load, apply, vi.fn());
    refresh.schedule("project");
    refresh.schedule("project");
    refresh.schedule("project");
    finish("old");
    await vi.waitFor(() =>
      expect(apply).toHaveBeenCalledWith("project", "new"),
    );
    expect(load).toHaveBeenCalledTimes(2);
    expect(apply).toHaveBeenCalledOnce();
    refresh.dispose();
  });
  it("suppresses results after removal or disposal", async () => {
    let finish!: (value: string) => void;
    const apply = vi.fn();
    const refresh = new LatestRefresh(
      () =>
        new Promise<string>((resolve) => {
          finish = resolve;
        }),
      apply,
      vi.fn(),
    );
    refresh.schedule("project");
    refresh.remove("project");
    finish("old");
    await Promise.resolve();
    expect(apply).not.toHaveBeenCalled();
    refresh.dispose();
    refresh.schedule("project");
    expect(apply).not.toHaveBeenCalled();
  });
  it("preserves a pending debounce while an earlier load completes", async () => {
    vi.useFakeTimers();
    let finish!: (value: string) => void;
    const load = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<string>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue("new");
    const apply = vi.fn();
    const refresh = new LatestRefresh<string>(load, apply, vi.fn());
    refresh.schedule("project");
    refresh.schedule("project", 400);
    finish("old");
    await vi.advanceTimersByTimeAsync(399);
    expect(apply).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(apply).toHaveBeenCalledWith("project", "new");
    refresh.dispose();
  });
});
