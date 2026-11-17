import { describe, expect, it, vi } from "vitest";
import { SpyTrace } from "../../src/spy/trace";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as fs from "node:fs";
vi.mock("node:fs", async (original) => ({ ...await original<typeof import("node:fs")>(), createWriteStream: vi.fn((await original<typeof import("node:fs")>()).createWriteStream) }));
describe("SpyTrace", () => {
  it("does not open a disabled trace", () => {
    vi.mocked(fs.createWriteStream).mockClear();
    const trace = new SpyTrace(); trace.configure(""); trace.message("toHost", {});
    expect(fs.createWriteStream).not.toHaveBeenCalled();
  });
  it("sanitizes both directions and logs RPCs", async () => {
    const dir = await mkdtemp(join(tmpdir(), "spy-trace-"));
    const file = join(dir, "trace");
    try {
      const trace = new SpyTrace(); trace.configure(file);
      trace.message("toHost", { type: "select" });
      trace.message("toWebview", { nodes: [{ nodeId: "a", info: { name: "x".repeat(501), rect: [1] }, properties: { secret: "value" }, image: "secret" }] });
      trace.rpc("inspect.properties", "a"); trace.dispose();
      await vi.waitFor(async () => expect((await readFile(file, "utf8")).trim().split("\n")).toHaveLength(3));
      const entries = (await readFile(file, "utf8")).trim().split("\n").map((line) => JSON.parse(line));
      expect(entries.map((entry) => entry.dir)).toEqual(["toHost", "toWebview", "rpc"]);
      expect(entries[1].msg.nodes[0]).toEqual({ nodeId: "a", info: { name: "x".repeat(500) } });
      expect(entries[2].params).toEqual({ nodeId: "a" });
    } finally { await rm(dir, { recursive: true, force: true }); }
  });
  it("swallows write errors", async () => {
    const trace = new SpyTrace(); trace.configure(join(tmpdir(), "missing-spy-trace-dir", "trace"));
    const circular: { self?: unknown } = {}; circular.self = circular;
    expect(() => trace.message("toHost", circular)).not.toThrow();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(() => trace.message("toHost", {})).not.toThrow(); trace.dispose();
  });
});
