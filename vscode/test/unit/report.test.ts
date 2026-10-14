import { describe, expect, it, vi } from "vitest";
vi.mock("vscode", () => ({}));
import { failureMessage, reportPath } from "../../src/report";

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
});
