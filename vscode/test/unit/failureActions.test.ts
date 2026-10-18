import { describe, expect, it, vi } from "vitest";

vi.mock("vscode", () => ({
  MarkdownString: class {
    value = "";
    isTrusted?: unknown;
    appendText(value: string) { this.value += value; }
    appendMarkdown(value: string) { this.value += value; }
    appendCodeblock(value: string) { this.value += value; }
  },
  TestMessage: class {
    location?: unknown;
    constructor(readonly message: unknown) {}
  },
  Uri: { file: (path: string) => ({ toString: () => "file:" + path }) },
  Position: class { constructor(readonly line: number, readonly character: number) {} },
  Location: class { constructor(readonly uri: unknown, readonly position: unknown) {} },
}));
import { failureMessages } from "../../src/testing/controller";

describe("native failure actions", () => {
  it("adds a trusted, explicit reveal action for a relocation path", () => {
    const messages = failureMessages({
      message: "Element not found",
      error: {
        diagnostic: {
          message: "Element not found",
          locator: "Button(automation_id='equals')",
          searchedIn: "Calculator",
          matchCount: 0,
          candidates: [],
          relocations: [
            {
              kind: "element",
              target: "equals",
              window: "Calculator",
              path: 'Window "Calculator" › Button #equals',
            },
          ],
        },
      },
    } as never);
    const message = messages[0] as unknown as {
      message: { value: string; isTrusted: unknown };
    };
    expect(message.message.value).toContain("Reveal relocated element in Spy");
    expect(message.message.value).toContain("command:wintestkit.spy.revealRelocation?");
    expect(message.message.isTrusted).toEqual({
      enabledCommands: ["wintestkit.spy.revealRelocation"],
    });
  });
});
