import { describe, expect, it, vi } from "vitest";
vi.mock("vscode", () => ({
  window: { showErrorMessage: vi.fn(async () => undefined), showInformationMessage: vi.fn(async () => undefined) },
  env: { openExternal: vi.fn(async () => true) },
}));
import { failureMessage, previewHtml, reportPath, Reports, waitForFile } from "../../src/report";
import type { Project } from "../../src/server/serverManager";

describe("report location", () => {
  it("prefers the last report of the session when it still exists", () => {
    expect(reportPath("C:/p/r/index.html", "x", "C:/p", () => true)).toBe(
      "C:/p/r/index.html",
    );
  });
  it("falls back to <root>/<report_dir>/index.html", () => {
    const found = (file: string) => file.endsWith("index.html");
    const result = reportPath(undefined, "wtk-report", "/proj", found);
    expect(result).toMatch(/wtk-report.index\.html$/);
  });
  it("returns undefined when nothing exists", () => {
    expect(
      reportPath("/gone/index.html", "wtk-report", "/proj", () => false),
    ).toBeUndefined();
    expect(
      reportPath(undefined, undefined, "/proj", () => true),
    ).toBeUndefined();
  });
  it("points a report's relative paths at its folder in the preview", () => {
    const base = "https://file+.vscode-resource.vscode-cdn.net/c%3A/p/report/";
    expect(previewHtml("<!doctype html><html><head><title>r</title></head></html>", base)).toContain(
      `<head><base href="${base}"><title>`,
    );
    expect(previewHtml("<p>no head</p>", base)).toBe(`<base href="${base}"><p>no head</p>`);
    expect(previewHtml("<head><meta></head>", 'x"y/')).toContain('href="x&quot;y/"');
  });
  it("waits for a report that is written after the run announces it", async () => {
    const sizes = [undefined, undefined, 10, 80, 80];
    const size = vi.fn(async () => sizes.shift());
    const sleep = vi.fn(async () => {});
    expect(await waitForFile("r/index.html", 15000, size, sleep)).toBe(true);
    expect(size).toHaveBeenCalledTimes(5);
    expect(await waitForFile("r/index.html", 300, async () => undefined, sleep)).toBe(false);
  });
  it("pluralizes the failure message", () => {
    expect(failureMessage(1)).toBe("1 test failed.");
    expect(failureMessage(3)).toBe("3 tests failed.");
  });
  it("keeps persisted last-run summaries scoped to each project and notifies the view", () => {
    const saved: Record<string, unknown> = {};
    const state = {
      get: (key: string) => saved[key],
      update: async (key: string, value: unknown) => { saved[key] = value; },
    };
    const reports = new Reports({} as never, {} as never, state as never);
    const first = { root: { toString: () => "file:///one", fsPath: "/one" } } as Project;
    const second = { root: { toString: () => "file:///two", fsPath: "/two" } } as Project;
    const changed = vi.fn();
    reports.onDidChange(changed);
    reports.record(first, "/one/report/index.html", 2, 7);
    reports.record(second, undefined, 0, 3);
    expect(reports.lastRun(first)).toMatchObject({ passed: 7, failed: 2, report: "/one/report/index.html" });
    expect(reports.lastRun(second)).toMatchObject({ passed: 3, failed: 0 });
    expect(reports.lastRun(undefined)).toBeUndefined();
    expect(changed).toHaveBeenCalledTimes(2);
    const restored = new Reports({} as never, {} as never, state as never);
    expect(restored.lastRun(first)).toMatchObject({ passed: 7, failed: 2 });
    reports.record(first, undefined, 0, 2);
    expect(reports.lastRun(first)).toMatchObject({ passed: 2, failed: 0 });
    expect(reports.lastRun(first)?.report).toBeUndefined();
  });
});
