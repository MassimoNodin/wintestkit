import { describe, expect, it } from "vitest";
import { appendRelocationAction, type TrustedMarkdown } from "../../src/testing/failureActions";

describe("native failure relocation action", () => {
  it("adds only the reveal command to the markdown trust allowlist", () => {
    const markdown = {
      value: "",
      appendMarkdown(value: string) { this.value += value; },
    } as TrustedMarkdown & { value: string };
    appendRelocationAction(markdown, {
      kind: "not_found",
      message: "Element not found",
      locator: "Button(automation_id='equals')",
      searchedIn: "Calculator",
      matchCount: 0,
      candidates: [],
      relocations: [{
        kind: "element",
        target: "equals",
        window: "Calculator",
        path: 'Window "Calculator" › Button #equals',
      }],
    });
    expect(markdown.value).toContain("Reveal relocated element in Spy");
    expect(markdown.value).toContain("command:wintestkit.spy.revealRelocation?");
    expect(markdown.isTrusted).toEqual({
      enabledCommands: ["wintestkit.spy.revealRelocation"],
    });
  });
});
