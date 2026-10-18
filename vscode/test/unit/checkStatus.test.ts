import { describe, expect, it } from "vitest";
import { summarizeChecks } from "../../src/editor/checkStatus";
import type { CheckResult } from "../../src/protocol/generated";

const result = (status: CheckResult["status"]): CheckResult => ({
  status,
  qualname: "Main.ok",
  durationMs: 1,
});

describe("summarizeChecks", () => {
  it("describes not found elements as state-dependent", () => {
    expect(
      summarizeChecks([result("found"), result("found"), result("not_found")]),
    ).toBe("Checked 3 elements: 2 found, 1 not found (possibly off-screen, broken, or moved).");
  });
  it("reports ambiguous and failed checks as errors", () => {
    expect(
      summarizeChecks([result("found"), result("ambiguous"), result("error")]),
    ).toBe("Checked 3 elements: 1 found, 0 not found (possibly off-screen, broken, or moved), 2 errors.");
  });
});
