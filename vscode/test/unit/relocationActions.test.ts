import { beforeEach, describe, expect, it, vi } from "vitest";

const registration = vi.hoisted(() => vi.fn(() => ({ dispose: vi.fn() })));
vi.mock("vscode", () => ({
  CodeActionKind: { QuickFix: { value: "quickfix" } },
  CodeAction: class {
    command?: unknown;
    constructor(readonly title: string, readonly kind: unknown) {}
  },
  Range: class {
    constructor(
      readonly startLine: number,
      readonly startCharacter: number,
      readonly endLine: number,
      readonly endCharacter: number,
    ) {}
    intersection(other: { startLine: number; endLine: number }) {
      return this.startLine <= other.endLine && this.endLine >= other.startLine
        ? this
        : undefined;
    }
  },
  languages: { registerCodeActionsProvider: registration },
}));
import { RelocationActions } from "../../src/editor/relocationActions";

describe("relocation code action", () => {
  beforeEach(() => registration.mockClear());
  it("offers a user initiated Spy reveal for a stored relocation", () => {
    const provider = new RelocationActions({
      entries: new Map([
        [
          "element",
          {
            page: { file: "C:/demo/pages/main.py" },
            element: {
              range: {
                start: { line: 4, character: 4 },
                end: { line: 4, character: 20 },
              },
            },
            result: {
              diagnostic: {
                relocations: [
                  { path: 'Window "Calc" › Button #equals' },
                ],
              },
            },
          },
        ],
      ]),
    } as never);
    const actions = provider.provideCodeActions(
      { uri: { fsPath: "c:\\demo\\pages\\main.py" } } as never,
      { startLine: 4, endLine: 4 } as never,
    );
    expect(actions).toHaveLength(1);
    expect(actions[0].command).toMatchObject({
      command: "wintestkit.spy.revealRelocation",
      arguments: ['Window "Calc" › Button #equals'],
    });
    provider.dispose();
  });
});
