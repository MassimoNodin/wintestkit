import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  panel: undefined as undefined | {
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
  info: vi.fn<(...args: unknown[]) => Promise<string | undefined>>(async () => undefined),
  openExternal: vi.fn(async () => true),
}));

vi.mock("vscode", () => ({
  Uri: { file: (fsPath: string) => ({ fsPath }) },
  ViewColumn: { Active: -1 },
  window: {
    createWebviewPanel: vi.fn(() => {
      mocks.panel = {
        webview: {
          html: "",
          onDidReceiveMessage: (handler) => {
            mocks.message = handler;
          },
          asWebviewUri: (uri) => ({ toString: () => "vscode-resource://" + uri.fsPath.replace(/\\/g, "/") }),
        },
        onDidDispose: () => {},
        reveal: () => {},
        dispose: () => {},
      };
      return mocks.panel;
    }),
    showSaveDialog: (...args: unknown[]) => mocks.saveDialog(...args),
    showInformationMessage: (...args: unknown[]) => mocks.info(...args),
    showErrorMessage: vi.fn(async () => undefined),
  },
  workspace: { getConfiguration: () => ({ get: (_key: string, fallback: unknown) => fallback }) },
  env: { openExternal: (...args: unknown[]) => (mocks.openExternal as (...a: unknown[]) => unknown)(...args) },
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

const reports = () => new Reports({} as never, { warn: vi.fn() } as never, undefined, template, 400);
const saveResults = (extra: object = {}) =>
  writeFile(
    path.join(dir, "results.json"),
    JSON.stringify({ version: 1, tests: [{ id: "t.py::a", name: "a", outcome: "passed" }], ...extra }),
  );

describe("report panel", () => {
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
});
