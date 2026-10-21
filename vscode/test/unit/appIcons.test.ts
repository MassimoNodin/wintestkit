import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseApplicationIcons } from "../../src/spy/appIcons";

const execution = vi.hoisted(() => ({
  run: vi.fn<(...args: unknown[]) => Promise<{ stdout: string }>>(),
}));
vi.mock("node:child_process", () => ({
  execFile: Object.assign(vi.fn(), {
    [Symbol.for("nodejs.util.promisify.custom")]: execution.run,
  }),
}));

const firstIcon = "data:image/png;base64,aGVsbG8=";
const secondIcon = "data:image/png;base64,d29ybGQ=";
const firstExe = "C:\\Apps\\First.exe";
const secondExe = "C:\\Apps\\Second.exe";
const platform = Object.getOwnPropertyDescriptor(process, "platform")!;
let readApplicationIcons: typeof import("../../src/spy/appIcons").readApplicationIcons;

function respond(value: unknown) {
  execution.run.mockResolvedValueOnce({ stdout: JSON.stringify(value) });
}

function scriptAt(index: number): string {
  const args = execution.run.mock.calls[index][1] as string[];
  return Buffer.from(args[args.length - 1], "base64").toString("utf16le");
}

beforeEach(async () => {
  execution.run.mockReset();
  vi.resetModules();
  Object.defineProperty(process, "platform", { ...platform, value: "win32" });
  ({ readApplicationIcons } = await import("../../src/spy/appIcons"));
});

afterEach(() => {
  Object.defineProperty(process, "platform", platform);
});

describe("Application icons", () => {
  it("accepts PNG data URIs keyed by numeric process IDs, including PowerShell BOM", () => {
    expect(
      parseApplicationIcons('\uFEFF{"123":"data:image/png;base64,aGVsbG8="}'),
    ).toEqual({ "123": "data:image/png;base64,aGVsbG8=" });
  });
  it("rejects external URLs, SVGs, invalid IDs and oversized values", () => {
    expect(
      parseApplicationIcons(
        JSON.stringify({
          "12": "https://example.com/icon.png",
          "13": "data:image/svg+xml;base64,abcd",
          "14": "data:image/png;base64," + "a".repeat(262144),
          "not-a-pid": "data:image/png;base64,abcd",
          "15": 42,
          "16": "data:image/png;base64,",
          "17": "data:image/png;base64,ab=c",
          "18": "data:image/png;base64,abcd\n",
          "19": "data:image/png;base64,abcd===",
        }),
      ),
    ).toEqual({});
  });
  it("rejects non-object payloads", () => {
    expect(parseApplicationIcons("null")).toEqual({});
    expect(parseApplicationIcons("[]")).toEqual({});
    expect(parseApplicationIcons('"text"')).toEqual({});
    expect(() => parseApplicationIcons("not JSON")).toThrow();
  });
  it("does not launch extraction for empty or invalid process IDs", async () => {
    expect(await readApplicationIcons([])).toEqual({});
    expect(
      await readApplicationIcons([
        0,
        -1,
        NaN,
        Infinity,
        1.5,
        Number.MAX_SAFE_INTEGER + 1,
      ]),
    ).toEqual({});
    expect(execution.run).not.toHaveBeenCalled();
  });

  it("does not launch PowerShell outside Windows", async () => {
    Object.defineProperty(process, "platform", { ...platform, value: "linux" });
    expect(await readApplicationIcons([12])).toEqual({});
    expect(execution.run).not.toHaveBeenCalled();
  });

  it("filters and deduplicates IDs and keeps PowerShell hidden and bounded", async () => {
    respond({ "12": firstExe, "99": secondExe });
    respond({ "0": firstIcon, "99": secondIcon });
    expect(await readApplicationIcons([12, 12, 0, -2, NaN, 1.5])).toEqual({
      "12": firstIcon,
    });
    expect(scriptAt(0)).toContain("foreach ($processId in @(12))");
    expect(scriptAt(0)).toContain("$process.MainModule.FileName");
    expect(scriptAt(0)).toContain("$process.Dispose()");
    expect(scriptAt(0)).not.toContain("ExtractAssociatedIcon");
    expect(scriptAt(1)).toContain("$files = @('c:\\apps\\first.exe')");
    expect(scriptAt(1)).toContain("$icon.Dispose()");
    expect(scriptAt(1)).toContain("$bitmap.Dispose()");
    expect(scriptAt(1)).toContain("$stream.Dispose()");
    for (const [executable, args, options] of execution.run.mock.calls) {
      expect(executable).toMatch(
        /WindowsPowerShell[\\/]v1\.0[\\/]powershell\.exe$/,
      );
      expect(args).toEqual([
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        expect.any(String),
      ]);
      expect(options).toEqual({
        windowsHide: true,
        timeout: 10000,
        maxBuffer: 8 * 1024 * 1024,
        encoding: "utf8",
      });
    }
  });

  it("reuses one extraction across calls, new instances, and Windows path casing", async () => {
    respond({ "11": firstExe, "12": "c:/APPS/First.exe" });
    respond({ "0": firstIcon });
    expect(await readApplicationIcons([11, 12])).toEqual({
      "11": firstIcon,
      "12": firstIcon,
    });
    respond({ "11": "C:\\APPS\\FIRST.EXE", "23": firstExe });
    expect(await readApplicationIcons([11, 23])).toEqual({
      "11": firstIcon,
      "23": firstIcon,
    });
    expect(execution.run).toHaveBeenCalledTimes(3);
    expect(scriptAt(2)).not.toContain("ExtractAssociatedIcon");
    expect(scriptAt(2)).not.toContain(firstIcon);
  });

  it("batches only uncached executables without serializing cached image bytes", async () => {
    respond({ "11": firstExe });
    respond({ "0": firstIcon });
    await readApplicationIcons([11]);
    respond({ "22": firstExe, "33": secondExe, "44": secondExe });
    respond({ "0": secondIcon });
    expect(await readApplicationIcons([22, 33, 44])).toEqual({
      "22": firstIcon,
      "33": secondIcon,
      "44": secondIcon,
    });
    expect(scriptAt(3)).toContain("$files = @('c:\\apps\\second.exe')");
    expect(scriptAt(3)).not.toContain("first.exe");
    expect(scriptAt(3)).not.toContain(firstIcon);
  });

  it("maps distinct batched executables to their own validated images", async () => {
    respond({ "11": firstExe, "22": secondExe, "33": firstExe });
    respond({ "0": firstIcon, "1": secondIcon });
    expect(await readApplicationIcons([11, 22, 33])).toEqual({
      "11": firstIcon,
      "22": secondIcon,
      "33": firstIcon,
    });
    expect(scriptAt(1)).toContain(
      "$files = @('c:\\apps\\first.exe','c:\\apps\\second.exe')",
    );
    expect(execution.run).toHaveBeenCalledTimes(2);
  });

  it("uses UTF-8 for executable lookups and accepts a PowerShell BOM", async () => {
    const executable = "C:\\Apps\\\u65e5\u672c.exe";
    execution.run.mockResolvedValueOnce({
      stdout: "\uFEFF" + JSON.stringify({ "11": executable }),
    });
    respond({ "0": firstIcon });
    expect(await readApplicationIcons([11])).toEqual({ "11": firstIcon });
    expect(scriptAt(0)).toContain(
      "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    );
    expect(scriptAt(1)).toContain(executable.toLowerCase());
  });

  it("shares in-flight extractions while isolating concurrent caller PID results", async () => {
    let finish!: (value: { stdout: string }) => void;
    const pending = new Promise<{ stdout: string }>((resolve) => {
      finish = resolve;
    });
    respond({ "11": firstExe, "12": firstExe });
    execution.run.mockReturnValueOnce(pending);
    respond({ "22": "c:\\APPS\\FIRST.exe", "33": secondExe });
    respond({ "0": secondIcon });
    const first = readApplicationIcons([11, 12]);
    await vi.waitFor(() => expect(execution.run).toHaveBeenCalledTimes(2));
    const second = readApplicationIcons([22, 33]);
    await vi.waitFor(() => expect(execution.run).toHaveBeenCalledTimes(4));
    expect(scriptAt(3)).toContain("$files = @('c:\\apps\\second.exe')");
    finish({ stdout: JSON.stringify({ "0": firstIcon }) });
    expect(await first).toEqual({ "11": firstIcon, "12": firstIcon });
    expect(await second).toEqual({ "22": firstIcon, "33": secondIcon });
    expect(execution.run).toHaveBeenCalledTimes(4);
  });

  it.each(["missing", "invalid", "malformed", "rejected"])(
    "retries %s extraction results instead of poisoning the cache",
    async (failure) => {
      respond({ "11": firstExe });
      if (failure === "missing") respond({});
      if (failure === "invalid")
        respond({ "0": "https://example.com/icon.png" });
      if (failure === "malformed")
        execution.run.mockResolvedValueOnce({ stdout: "not JSON" });
      if (failure === "rejected")
        execution.run.mockRejectedValueOnce(new Error("timed out"));
      expect(await readApplicationIcons([11])).toEqual({});
      respond({ "22": firstExe });
      respond({ "0": firstIcon });
      expect(await readApplicationIcons([22])).toEqual({ "22": firstIcon });
      expect(execution.run).toHaveBeenCalledTimes(4);
    },
  );

  it("retains successful entries when another executable in the batch fails", async () => {
    respond({ "11": firstExe, "22": secondExe });
    respond({ "0": firstIcon });
    expect(await readApplicationIcons([11, 22])).toEqual({ "11": firstIcon });
    respond({ "11": firstExe, "22": secondExe });
    respond({ "0": secondIcon });
    expect(await readApplicationIcons([11, 22])).toEqual({
      "11": firstIcon,
      "22": secondIcon,
    });
    expect(scriptAt(3)).toContain("$files = @('c:\\apps\\second.exe')");
  });

  it("resolves reused PIDs again and omits exited or inaccessible processes", async () => {
    respond({ "11": firstExe });
    respond({ "0": firstIcon });
    expect(await readApplicationIcons([11])).toEqual({ "11": firstIcon });
    respond({ "11": secondExe });
    respond({ "0": secondIcon });
    expect(await readApplicationIcons([11])).toEqual({ "11": secondIcon });
    respond({});
    expect(await readApplicationIcons([11])).toEqual({});
    respond({ "11": firstExe });
    expect(await readApplicationIcons([11])).toEqual({ "11": firstIcon });
    expect(execution.run).toHaveBeenCalledTimes(6);
  });

  it.each(["null", "[]", "not JSON"])(
    "ignores invalid executable lookup output: %s",
    async (stdout) => {
      execution.run.mockResolvedValueOnce({ stdout });
      expect(await readApplicationIcons([11])).toEqual({});
      expect(execution.run).toHaveBeenCalledTimes(1);
    },
  );

  it("retries failed lookups and never falls back to a stale PID icon", async () => {
    respond({ "11": firstExe });
    respond({ "0": firstIcon });
    await readApplicationIcons([11]);
    execution.run.mockRejectedValueOnce(new Error("access denied"));
    expect(await readApplicationIcons([11])).toEqual({});
    respond({ "11": firstExe });
    expect(await readApplicationIcons([11])).toEqual({ "11": firstIcon });
    expect(execution.run).toHaveBeenCalledTimes(4);
  });

  it("ignores invalid paths and lookup entries outside the caller's PID set", async () => {
    respond({
      "11": "",
      "12": 42,
      "13": "relative.exe",
      "14": "C:\\bad\0.exe",
      "99": firstExe,
    });
    expect(await readApplicationIcons([11, 12, 13, 14])).toEqual({});
    expect(execution.run).toHaveBeenCalledTimes(1);
  });

  it("quotes executable paths as PowerShell literals", async () => {
    respond({ "11": "C:\\App's\\$tool.exe" });
    respond({ "0": firstIcon });
    expect(await readApplicationIcons([11])).toEqual({ "11": firstIcon });
    expect(scriptAt(1)).toContain("$files = @('c:\\app''s\\$tool.exe')");
  });

  it("starts a fresh cache when the extension-host module reloads", async () => {
    respond({ "11": firstExe });
    respond({ "0": firstIcon });
    await readApplicationIcons([11]);
    vi.resetModules();
    ({ readApplicationIcons } = await import("../../src/spy/appIcons"));
    respond({ "11": firstExe });
    respond({ "0": secondIcon });
    expect(await readApplicationIcons([11])).toEqual({ "11": secondIcon });
    expect(execution.run).toHaveBeenCalledTimes(4);
  });
});
