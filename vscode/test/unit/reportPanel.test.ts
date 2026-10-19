import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  panel: undefined as
    | undefined
    | {
        webview: {
          html: string;
          onDidReceiveMessage: (handler: (message: unknown) => void) => void;
          asWebviewUri: (uri: { fsPath: string }) => { toString: () => string };
        };
        onDidDispose: (handler: () => void) => void;
        reveal: () => void;
        dispose: () => void;
      },
  message: undefined as undefined | ((message: unknown) => void),
  saveDialog: vi.fn(),
  info: vi.fn<(...args: unknown[]) => Promise<string | undefined>>(
    async () => undefined,
  ),
  openExternal: vi.fn(async () => true),
  pick: vi.fn(),
}));

vi.mock("vscode", () => ({
  Uri: { file: (fsPath: string) => ({ fsPath }) },
  ViewColumn: { Active: -1 },
  window: {
    createWebviewPanel: vi.fn(() => {
      let onDispose: (() => void) | undefined;
      mocks.panel = {
        webview: {
          html: "",
          onDidReceiveMessage: (handler) => {
            mocks.message = handler;
          },
          asWebviewUri: (uri) => ({ toString: () => "vscode-resource://" + uri.fsPath.replace(/\\/g, "/") }),
        },
        onDidDispose: (handler) => { onDispose = handler; },
        reveal: () => {},
        dispose: vi.fn(() => onDispose?.()),
      };
      return mocks.panel;
    }),
    showSaveDialog: (...args: unknown[]) => mocks.saveDialog(...args),
    showQuickPick: (...args: unknown[]) => mocks.pick(...args),
    showInformationMessage: (...args: unknown[]) => mocks.info(...args),
    showErrorMessage: vi.fn(async () => undefined),
  },
  workspace: {
    getConfiguration: () => ({
      get: (_key: string, fallback: unknown) => fallback,
    }),
  },
  env: {
    openExternal: (...args: unknown[]) =>
      (mocks.openExternal as (...a: unknown[]) => unknown)(...args),
  },
}));

import { Reports } from "../../src/report";

const TEMPLATE =
  '<html><head></head><body><script type="application/json" id="wtk-data">__WTK_DATA__</script></body></html>';

let dir: string;
let template: string;
beforeEach(async () => {
  vi.clearAllMocks();
  mocks.panel = undefined;
  mocks.message = undefined;
  dir = await mkdtemp(path.join(tmpdir(), "wtk-panel-"));
  template = path.join(dir, "template.html");
  await writeFile(template, TEMPLATE);
});
afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

const reports = () =>
  new Reports(
    {} as never,
    { warn: vi.fn() } as never,
    undefined,
    template,
    400,
  );
const saveResults = (extra: object = {}) =>
  writeFile(
    path.join(dir, "results.json"),
    JSON.stringify({
      version: 1,
      tests: [{ id: "t.py::a", name: "a", outcome: "passed" }],
      ...extra,
    }),
  );

async function storeRun(
  instance: Reports,
  name: string,
  folder: string,
  counts?: { failed: number; passed: number },
) {
  const runDir = path.join(dir, "runs", folder);
  await mkdir(runDir, { recursive: true });
  await writeFile(
    path.join(runDir, "results.json"),
    JSON.stringify({
      version: 1,
      tests: [{ id: "t.py::" + folder, name: folder, outcome: "passed" }],
    }),
  );
  instance.history.start(name, "file:///project", "project", runDir);
  if (counts) instance.history.finish(name, "file:///project", counts);
  return runDir;
}

describe("report panel", () => {
  it("invalidates cached totals and closes the report when its saved run is deleted", async () => {
    const instance = reports();
    const runDir = await storeRun(instance, "cleared", "cleared");
    const project = { root: { toString: () => "file:///project" } } as never;
    instance.record(project, path.join(runDir, "index.html"), 0, 1);
    await instance.preview(path.join(runDir, "index.html"));
    const panel = mocks.panel!;
    expect(await instance.reportedTestIds(project)).toEqual(new Set(["t.py::cleared"]));
    await instance.history.discard("cleared");
    expect(panel.dispose).toHaveBeenCalledOnce();
    expect(instance.lastRun(project)).toBeUndefined();
    expect(await instance.reportedTestIds(project)).toEqual(new Set());
    expect(instance.history.list()).toEqual([]);
  });

  it("draws the report from results.json when no index.html was written", async () => {
    await saveResults();
    await reports().preview(path.join(dir, "index.html"));
    expect(mocks.panel?.webview.html).toContain('"id":"t.py::a"');
    expect(mocks.panel?.webview.html).toContain("<base href=");
    expect(mocks.panel?.webview.html).not.toContain("__WTK_DATA__");
  });

  it("shows an older run's index.html when it has no results.json", async () => {
    await writeFile(path.join(dir, "index.html"), "<html><head></head><body>old report</body></html>");
    await reports().preview(path.join(dir, "index.html"));
    expect(mocks.panel?.webview.html).toContain("old report");
  });

  it("fails when neither results nor a page exist", async () => {
    await expect(reports().preview(path.join(dir, "index.html"))).rejects.toThrow("was not written");
  });

  it("exports a self-contained HTML file when the page asks, into the report folder by default", async () => {
    await saveResults();
    const target = path.join(dir, "exported.html");
    mocks.saveDialog.mockResolvedValue({ fsPath: target });
    mocks.info.mockResolvedValue("Open in Browser");
    await reports().preview(path.join(dir, "index.html"));
    mocks.message?.({ type: "wtk-export" });
    await vi.waitFor(() => expect(mocks.openExternal).toHaveBeenCalled());
    expect(mocks.saveDialog.mock.calls[0][0]).toMatchObject({
      defaultUri: { fsPath: path.join(dir, "index.html") },
    });
    const saved = await readFile(target, "utf8");
    expect(saved).toContain('"id":"t.py::a"');
    expect(saved).not.toContain("<base href=");
    expect(String(mocks.info.mock.calls[0][0])).not.toContain("keep that folder");
  });

  it("says where the screenshots live when the export leaves the report folder, and does nothing when cancelled", async () => {
    await saveResults();
    const other = await mkdtemp(path.join(tmpdir(), "wtk-export-"));
    try {
      const target = path.join(other, "copy.html");
      mocks.saveDialog.mockResolvedValueOnce({ fsPath: target });
      const instance = reports();
      await instance.preview(path.join(dir, "index.html"));
      await instance.exportHtml();
      expect(String(mocks.info.mock.calls[0][0])).toContain(path.join(dir, "artifacts"));
      expect(await readFile(target, "utf8")).toContain('"id":"t.py::a"');
      mocks.saveDialog.mockResolvedValueOnce(undefined);
      mocks.info.mockClear();
      await instance.exportHtml();
      expect(mocks.info).not.toHaveBeenCalled();
    } finally {
      await rm(other, { recursive: true, force: true });
    }
  });

  it("opens the report of the run named by a clicked test row, not the latest one", async () => {
    const instance = reports();
    await storeRun(instance, "WinTestKit run A", "a");
    await storeRun(instance, "WinTestKit run B", "b");
    await instance.openRun("WinTestKit run A", "file:///project");
    expect(mocks.panel?.webview.html).toContain('"id":"t.py::a"');
    expect(mocks.panel?.webview.html).not.toContain('"id":"t.py::b"');
  });

  it("selects the exact clicked parameterized test in its run", async () => {
    const instance = reports();
    await storeRun(instance, "WinTestKit run A", "a");
    const testId = 'tests/t.py::test_ok[a & "b"/雪]';
    await writeFile(path.join(dir, "runs", "a", "results.json"), JSON.stringify({
      version: 1,
      tests: [{ id: "t.py::a", outcome: "failed" }, { id: testId, outcome: "passed" }],
    }));
    await instance.openRun("WinTestKit run A", "file:///project", testId);
    expect(mocks.panel?.webview.html).toContain(`<meta name="wtk-test" content="${encodeURIComponent(testId)}">`);
    await instance.openRun("WinTestKit run A", "file:///project", "t.py::a");
    expect(mocks.panel?.webview.html).toContain(`content="${encodeURIComponent("t.py::a")}"`);
    expect(mocks.panel?.webview.html).not.toContain(encodeURIComponent(testId));
    await instance.preview(path.join(dir, "runs", "a", "index.html"));
    expect(mocks.panel?.webview.html).not.toContain('name="wtk-test"');
  });

  it("opens file and parameterized group rows at a matching failure", async () => {
    const instance = reports();
    const runDir = await storeRun(instance, "WinTestKit run A", "a");
    await writeFile(path.join(runDir, "results.json"), JSON.stringify({
      version: 1,
      tests: [
        { id: "other.py::test_a", outcome: "failed" },
        { id: "t.py::test_a[ok]", outcome: "passed" },
        { id: "t.py::test_a[bad]", outcome: "failed" },
      ],
    }));
    const project = { root: { toString: () => "file:///project" } };
    for (const testId of ["t.py", "t.py::test_a"]) {
      await instance.openTest(project as never, testId);
      expect(mocks.panel?.webview.html).toContain(`content="${encodeURIComponent("t.py::test_a[bad]")}"`);
    }
    await instance.openTest(project as never, "t.py::test_a[ok]");
    expect(mocks.panel?.webview.html).toContain(`content="${encodeURIComponent("t.py::test_a[ok]")}"`);
  });

  it("opens the newest retained run containing the sidebar test, skipping other projects and partial runs", async () => {
    const instance = reports();
    await storeRun(instance, "WinTestKit run A", "a");
    await new Promise((resolve) => setTimeout(resolve, 5));
    await storeRun(instance, "WinTestKit run B", "b");
    const project = { root: { toString: () => "file:///project" } };
    await instance.openTest(project as never, "t.py::a");
    expect(mocks.panel?.webview.html).toContain('"name":"a"');
    expect(mocks.panel?.webview.html).toContain(`content="${encodeURIComponent("t.py::a")}"`);
    expect(mocks.panel?.webview.html).not.toContain('"name":"b"');
    mocks.info.mockClear();
    await instance.openTest({ root: { toString: () => "file:///other" } } as never, "t.py::a");
    await instance.openTest(project as never, "t.py::absent");
    expect(mocks.info).toHaveBeenCalledTimes(2);
    expect(String(mocks.info.mock.calls[0][0])).toContain("No stored WinTestKit report contains this test");
  });

  it("does not substitute a different project's report for an explicit project", async () => {
    const instance = reports();
    await storeRun(instance, "WinTestKit run A", "a");
    await instance.openRun("WinTestKit run A", "file:///other", "t.py::a");
    expect(mocks.panel).toBeUndefined();
    expect(mocks.info).toHaveBeenCalled();
  });

  it("asks which project when a multi-project run's row does not say", async () => {
    const instance = reports();
    const runDir = await storeRun(instance, "WinTestKit run M", "m1");
    const second = path.join(dir, "runs", "m2");
    await mkdir(second, { recursive: true });
    await writeFile(
      path.join(second, "results.json"),
      JSON.stringify({
        version: 1,
        tests: [{ id: "t.py::m2", outcome: "passed" }],
      }),
    );
    instance.history.start(
      "WinTestKit run M",
      "file:///other",
      "other",
      second,
    );
    mocks.pick.mockImplementation(async (items: { label: string }[]) =>
      items.find((item) => item.label === "other"),
    );
    await instance.openRun("WinTestKit run M");
    expect(runDir).not.toBe(second);
    expect(mocks.panel?.webview.html).toContain('"id":"t.py::m2"');
    mocks.pick.mockClear();
    await instance.openRun("WinTestKit run M", "file:///project");
    expect(mocks.pick).not.toHaveBeenCalled();
  });

  it("explains when a run's report has been removed instead of opening anything", async () => {
    const instance = reports();
    await instance.openRun("WinTestKit run gone");
    await instance.openRun(undefined);
    expect(mocks.panel).toBeUndefined();
    expect(String(mocks.info.mock.calls[0][0])).toContain(
      "no longer available",
    );
  });

  it("does not open a WinTestKit report for another provider's run", async () => {
    const instance = reports();
    await storeRun(instance, "WinTestKit run A", "a");
    await instance.openRun("Running Tests for Workspace(s): project");
    expect(mocks.panel).toBeUndefined();
    expect(mocks.pick).not.toHaveBeenCalled();
    expect(String(mocks.info.mock.calls[0][0])).toContain(
      "No WinTestKit report",
    );
  });

  it("asks which project after selecting a multi-project run from history", async () => {
    const instance = reports();
    await storeRun(instance, "WinTestKit run M", "m1");
    const second = path.join(dir, "runs", "m2");
    await mkdir(second, { recursive: true });
    await writeFile(
      path.join(second, "results.json"),
      JSON.stringify({
        version: 1,
        tests: [{ id: "other-project", outcome: "passed" }],
      }),
    );
    instance.history.start(
      "WinTestKit run M",
      "file:///other",
      "other",
      second,
    );
    mocks.pick.mockImplementationOnce(
      async (items: { run: unknown }[]) => items[0],
    );
    mocks.pick.mockImplementationOnce(async (items: { label: string }[]) =>
      items.find((item) => item.label === "other"),
    );
    await instance.openPrevious();
    expect(mocks.pick).toHaveBeenCalledTimes(2);
    expect(mocks.panel?.webview.html).toContain('"id":"other-project"');
  });

  it("lists earlier runs newest first with their totals, and opens the one picked", async () => {
    const instance = reports();
    const first = instance.history.newName();
    await storeRun(instance, first, "first", { failed: 1, passed: 5 });
    await new Promise((resolve) => setTimeout(resolve, 5));
    const second = instance.history.newName();
    await storeRun(instance, second, "second", { failed: 0, passed: 6 });
    mocks.pick.mockImplementation(
      async (items: { description: string; run: { name: string } }[]) =>
        items[1],
    );
    await instance.openPrevious();
    const items = mocks.pick.mock.calls[0][0] as {
      label: string;
      description: string;
      detail: string;
    }[];
    expect(items.map((item) => item.description)).toEqual([
      "6 passed",
      "1 failed · 5 passed",
    ]);
    expect(items[0].label).toContain("$(pass)");
    expect(items[1].label).toContain("$(error)");
    expect(items[0].detail).toBe("project");
    expect(mocks.panel?.webview.html).toContain('"id":"t.py::first"');
  });

  it("says so when no earlier run is stored", async () => {
    await reports().openPrevious();
    expect(mocks.pick).not.toHaveBeenCalled();
    expect(String(mocks.info.mock.calls[0][0])).toContain("No earlier");
  });
});
