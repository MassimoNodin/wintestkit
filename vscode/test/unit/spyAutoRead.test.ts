import { afterEach, describe, expect, it, vi } from "vitest";
import type { ManagedInspector } from "../../src/spy/managedSession";
const mocks = vi.hoisted(() => ({ warning: vi.fn() }));
vi.mock("vscode", () => ({ window: { showWarningMessage: mocks.warning }, env: { clipboard: { writeText: vi.fn() } }, workspace: { getConfiguration: () => ({ get: () => false, update: vi.fn() }) }, Uri: { file: (path: string) => path } }));
import { AUTO_BATCH, AUTO_BUDGET_MS, ManagedPanel } from "../../src/spy/managedPanel";

type Paths = { objectId: string; paths: { name: string }[][] };
type Sent = { rows: { value?: { status: string; scalar?: string }; autoStatus?: string }[] };
const member = (name: string) => ({ memberKey: name, name, category: "clrProperty", declaringType: "T", declaredType: "T", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "property", name } });
const values = (p: Paths) => ({ result: { values: p.paths.map(([{ name }]) => ({ value: { status: "ok", kind: "string", scalar: name } })) } });

function make(count: number, options: { spyRead?: (p: Paths, background?: boolean) => Promise<unknown>; yieldToUser?: () => Promise<number> } = {}) {
  const spyRead = vi.fn(options.spyRead ?? (async (p: Paths) => values(p)));
  const yieldToUser = vi.fn(options.yieldToUser ?? (async () => 0));
  const inspector = {
    visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), clearSpy: async () => {}, bindSpy: async () => false, bindings: vi.fn(),
    resolve: vi.fn(async (node: string) => ({ status: "exact", object: { objectId: node, generation: 1 } })),
    members: vi.fn(async (p: { objectId: string }) => ({ items: Array.from({ length: count }, (_, index) => member(`${p.objectId}${index}`)), complete: true })),
    spyRead, yieldToUser,
  };
  const send = vi.fn();
  const panel = new ManagedPanel(inspector as unknown as ManagedInspector, send);
  const last = () => send.mock.calls.at(-1)![0] as Sent;
  return { inspector, panel, send, spyRead, yieldToUser, last };
}
const settled = (rows: Sent["rows"]) => rows.map((row) => row.value ? row.value.status : row.autoStatus ?? "unread");

afterEach(() => { vi.useRealTimers(); mocks.warning.mockReset().mockResolvedValue("Read automatically"); });
mocks.warning.mockResolvedValue("Read automatically");

describe("automatic read batching", () => {
  it("reads many rows per request, never more than the batch size, as background work", async () => {
    const { panel, spyRead, last } = make(60);
    panel.select("node");
    await vi.waitFor(() => expect(settled(last().rows).filter((status) => status === "ok")).toHaveLength(60));
    expect(AUTO_BATCH).toBe(25);
    expect(spyRead.mock.calls.map(([p]) => p.paths.length)).toEqual([25, 25, 10]);
    expect(spyRead.mock.calls.every(([, background]) => background === true)).toBe(true);
    expect(spyRead.mock.calls[0][0].paths[0][0].name).toBe("node0");
  });

  it("sends one request for an object with a few rows", async () => {
    const { panel, spyRead, last } = make(3);
    panel.select("node");
    await vi.waitFor(() => expect(settled(last().rows)).toEqual(["ok", "ok", "ok"]));
    expect(spyRead).toHaveBeenCalledTimes(1);
  });
});

describe("automatic read yields and cancels", () => {
  it("waits for a pending user action between batches", async () => {
    let release!: (waited: number) => void;
    const gate = new Promise<number>((resolve) => { release = resolve; });
    const { panel, spyRead, yieldToUser, last } = make(60, { yieldToUser: vi.fn().mockResolvedValueOnce(0).mockReturnValueOnce(gate).mockResolvedValue(0) as () => Promise<number> });
    panel.select("node");
    await vi.waitFor(() => expect(spyRead).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(yieldToUser).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(spyRead).toHaveBeenCalledTimes(1);
    release(500);
    await vi.waitFor(() => expect(settled(last().rows).filter((status) => status === "ok")).toHaveLength(60));
    expect(spyRead).toHaveBeenCalledTimes(3);
  });

  it("stops at once when another object is selected and never writes the old values into the new rows", async () => {
    let finish!: (value: unknown) => void;
    const { panel, spyRead, last } = make(60, { spyRead: (p) => p.objectId === "old" ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve(values(p)) });
    panel.select("old");
    await vi.waitFor(() => expect(spyRead).toHaveBeenCalledTimes(1));
    panel.select("new");
    await vi.waitFor(() => expect(settled(last().rows).filter((status) => status === "ok")).toHaveLength(60));
    finish(values(spyRead.mock.calls[0][0]));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(spyRead.mock.calls.filter(([p]) => p.objectId === "old")).toHaveLength(1);
    expect(spyRead.mock.calls.filter(([p]) => p.objectId === "new").map(([p]) => p.paths.length)).toEqual([25, 25, 10]);
    expect(last().rows.map((row) => row.value?.scalar).every((scalar) => scalar?.startsWith("new"))).toBe(true);
  });

  it("a cancelled read leaves its rows as read so far, not timed out, and resumes where it stopped", async () => {
    const { panel, spyRead, yieldToUser, last } = make(60);
    yieldToUser.mockResolvedValueOnce(0).mockImplementationOnce(async () => { panel.pauseAutoRead(); return 0; });
    panel.select("node");
    await vi.waitFor(() => expect(yieldToUser).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(spyRead).toHaveBeenCalledTimes(1);
    expect(settled(last().rows)).toEqual([...Array(25).fill("ok"), ...Array(35).fill("unread")]);
    panel.resumeAutoRead();
    await vi.waitFor(() => expect(settled(last().rows).filter((status) => status === "ok")).toHaveLength(60));
    expect(spyRead.mock.calls.map(([p]) => p.paths.length)).toEqual([25, 25, 10]);
    expect(spyRead.mock.calls[1][0].paths[0][0].name).toBe("node25");
  });

  it("resume does nothing when everything was read", async () => {
    const { panel, spyRead, last } = make(3);
    panel.select("node");
    await vi.waitFor(() => expect(settled(last().rows)).toEqual(["ok", "ok", "ok"]));
    panel.resumeAutoRead();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(spyRead).toHaveBeenCalledTimes(1);
  });
});

describe("automatic read time budget", () => {
  it("gives one object 5 s of reading and marks every row it did not reach as timed out", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const { panel, spyRead, last } = make(100, { spyRead: (p) => new Promise((resolve) => setTimeout(() => resolve(values(p)), 2000)) });
    panel.select("node");
    await vi.advanceTimersByTimeAsync(AUTO_BUDGET_MS + 200);
    expect(spyRead).toHaveBeenCalledTimes(3);
    expect(settled(last().rows)).toEqual([...Array(50).fill("ok"), ...Array(50).fill("timed out")]);
  });

  it("does not spend the budget while it waits for the user", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const wait = () => new Promise<number>((resolve) => setTimeout(() => resolve(3000), 3000));
    const { panel, last } = make(100, { yieldToUser: wait, spyRead: (p) => new Promise((resolve) => setTimeout(() => resolve(values(p)), 1000)) });
    panel.select("node");
    await vi.advanceTimersByTimeAsync(4 * (3000 + 1000) + 100);
    expect(settled(last().rows)).toEqual(Array(100).fill("ok"));
  });

  it("a hung request ends at the budget and the later rows are not sent", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const { panel, spyRead, last } = make(60, { spyRead: () => new Promise(() => {}) });
    panel.select("node");
    await vi.advanceTimersByTimeAsync(AUTO_BUDGET_MS + 100);
    expect(spyRead).toHaveBeenCalledTimes(1);
    expect(settled(last().rows)).toEqual(Array(60).fill("timed out"));
  });
});
