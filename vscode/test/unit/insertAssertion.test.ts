import { beforeEach, describe, expect, it, vi } from "vitest";
import { assertionLine } from "../../src/spy/assertionModel";

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

const state = vi.hoisted(() => ({
  handler: undefined as ((observed: { name: string; enabled: boolean }) => Promise<void>) | undefined,
  quickPick: vi.fn(async () => ({ label: "Text" })),
  input: vi.fn(async () => "page.result"),
  confirm: vi.fn(async () => undefined as string | undefined),
  edits: [] as string[],
  docText: "def test_result():\n    pass\n",
}));
vi.mock("vscode", () => ({
  EndOfLine: { CRLF: 2 },
  Position: class { constructor(readonly line: number, readonly character: number) {} },
  window: {
    get activeTextEditor() {
      return {
        document: {
          languageId: "python",
          eol: 1,
          getText: () => state.docText,
          lineAt: () => ({ text: "    pass" }),
        },
        selection: { active: { line: 1 } },
        edit: async (callback: (edit: { insert: (_position: unknown, text: string) => void }) => void) => {
          const edit = { insert: (_position: unknown, text: string) => state.edits.push(text) };
          callback(edit);
          return true;
        },
      };
    },
    showWarningMessage: vi.fn(),
    showQuickPick: state.quickPick,
    showInputBox: state.input,
    showInformationMessage: state.confirm,
  },
  commands: {
    registerCommand: (_name: string, handler: typeof state.handler) => {
      state.handler = handler;
      return { dispose: vi.fn() };
    },
  },
}));
import { registerInsertAssertion } from "../../src/spy/insertAssertion";

describe("confirmed Spy assertion insertion", () => {
  beforeEach(() => {
    state.edits.length = 0;
    state.docText = "def test_result():\n    pass\n";
    state.quickPick.mockResolvedValue({ label: "Text" });
    state.input.mockResolvedValue("page.result");
    state.confirm.mockResolvedValue(undefined);
    registerInsertAssertion();
  });

  it("shows observed values and inserts nothing when preview is cancelled", async () => {
    await state.handler?.({ name: "7", enabled: true });
    expect(state.quickPick).toHaveBeenCalledWith(
      [{ label: "Text", description: 'to_have_text("7")' }, { label: "Enabled state", description: "to_be_enabled()" }],
      expect.any(Object),
    );
    expect(state.confirm).toHaveBeenCalledWith(
      'expect(page.result).to_have_text("7")',
      expect.objectContaining({ modal: true }),
      "Insert",
    );
    expect(state.edits).toEqual([]);
  });

  it("inserts the confirmed line and public expect import", async () => {
    state.confirm.mockResolvedValue("Insert");
    await state.handler?.({ name: "7", enabled: false });
    expect(state.edits).toEqual([
      "    from wintestkit import expect\n    expect(page.result).to_have_text(\"7\")\n",
    ]);
  });
});
