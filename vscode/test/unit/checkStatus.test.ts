import { describe, expect, it } from "vitest";
import { summarizeChecks } from "../../src/editor/checkStatus";
import type { CheckResult } from "../../src/protocol/generated";

const result = (status: CheckResult["status"]): CheckResult => ({
  status,
  qualname: "Main.ok",
  durationMs: 1,
});

describe("summarizeChecks", () => {
  it("counts not found elements as broken/moved", () => {
    expect(
      summarizeChecks([result("found"), result("found"), result("not_found")]),
    ).toBe("Checked 3 elements: 2 found, 1 broken/moved.");
  });
  it("reports ambiguous and failed checks as errors", () => {
    expect(
      summarizeChecks([result("found"), result("ambiguous"), result("error")]),
    ).toBe("Checked 3 elements: 1 found, 0 broken/moved, 2 errors.");
  });
});
