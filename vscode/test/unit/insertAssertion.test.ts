import { describe, expect, it } from "vitest";
import { assertionLine } from "../../src/spy/insertAssertion";

describe("Spy assertion snippets", () => {
  it("uses only the observed text or enabled state with public expect APIs", () => {
    expect(assertionLine("text", "page.result", "7")).toBe(
      'expect(page.result).to_have_text("7")',
    );
    expect(assertionLine("enabled", "page.submit", true)).toBe(
      "expect(page.submit).to_be_enabled()",
    );
    expect(assertionLine("enabled", "page.submit", false)).toBe(
      "expect(page.submit).to_be_disabled()",
    );
  });
});
