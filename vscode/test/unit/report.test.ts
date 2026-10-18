import { describe, expect, it, vi } from "vitest";
vi.mock("vscode", () => ({
  window: { showErrorMessage: vi.fn(async () => undefined), showInformationMessage: vi.fn(async () => undefined) },
  env: { openExternal: vi.fn(async () => true) },
}));
import { failureMessage, reportPath, Reports } from "../../src/report";
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
