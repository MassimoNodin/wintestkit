import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  decorate: vi.fn(),
  styles: [] as unknown[],
  styleOptions: [] as object[],
}));
vi.mock("vscode", () => ({
  languages: { createDiagnosticCollection: () => ({ clear: vi.fn(), set: vi.fn(), dispose: vi.fn() }) },
  Uri: { file: (fsPath: string) => ({ fsPath }) },
  ThemeColor: class {},
  Range: class {
    constructor(readonly startLine: number, readonly startCharacter: number, readonly endLine: number, readonly endCharacter: number) {}
  },
  Diagnostic: class {
    source?: string;
    constructor(readonly range: unknown, readonly message: string, readonly severity: number) {}
  },
  DiagnosticSeverity: { Warning: 1 },
  window: {
    visibleTextEditors: [{ document: { uri: { fsPath: "c:\\demo\\pages\\main.py" } }, setDecorations: mocks.decorate }],
    createTextEditorDecorationType: (options: object) => {
      mocks.styleOptions.push(options);
      const style = { dispose: vi.fn() };
      mocks.styles.push(style);
      return style;
    },
    onDidChangeVisibleTextEditors: () => ({ dispose: vi.fn() }),
  },
}));
import { CheckDecorations } from "../../src/editor/decorations";

const entry = (status: string, extra: object = {}) => ({
  page: { file: "C:/demo/pages/main.py" },
  element: { range: { start: { line: 4 } }, nameRange: { start: { line: 4, character: 0 }, end: { line: 4, character: 6 } } },
  result: { status, ...extra },
});
const create = (...entries: ReturnType<typeof entry>[]) => {
  let refresh = () => {};
  const decorations = new CheckDecorations({
    entries: new Map(entries.map((item, index) => [String(index), item])),
    onDidChange: (listener: () => void) => { refresh = listener; return { dispose: vi.fn() }; },
  } as never);
  refresh();
  return decorations;
};

describe("Windows backend editor paths", () => {
  it("decorates a native lowercase-drive document for a POSIX backend path", () => {
    mocks.decorate.mockClear();
    mocks.styles.length = 0;
    const decorations = create(entry("not_found"));
    expect(mocks.decorate).toHaveBeenCalledWith(mocks.styles[0], [expect.objectContaining({
      renderOptions: { after: { contentText: "  \u2717 not found" } },
    })]);
    decorations.dispose();
  });
});

describe("check decorations", () => {
  it("draws no gutter icon for any status", () => {
    mocks.styleOptions.length = 0;
    create(entry("found")).dispose();
    expect(mocks.styleOptions).toHaveLength(3);
    for (const options of mocks.styleOptions) {
      expect(options).not.toHaveProperty("gutterIconPath");
      expect(options).not.toHaveProperty("gutterIconSize");
    }
  });

  it("marks no gutter tick or inline text on a passing element", () => {
    mocks.decorate.mockClear();
    mocks.styles.length = 0;
    const decorations = create(entry("found"));
    expect(mocks.styles).toHaveLength(3); // there is no style for a passing element
    for (const [, options] of mocks.decorate.mock.calls) expect(options).toEqual([]);
    decorations.dispose();
  });

  it("puts the text after the code on the element's first line, never before it", () => {
    mocks.decorate.mockClear();
    mocks.styles.length = 0;
    const decorations = create(entry("not_found"));
    const options = mocks.decorate.mock.calls.flatMap(([, list]) => list as Array<{ range: Record<string, number> }>);
    expect(options).toHaveLength(1);
    expect(options[0].range).toMatchObject({ startLine: 4, endLine: 4 });
    expect(options[0].range.startCharacter).toBeGreaterThan(1_000_000);
    expect(options[0].range.endCharacter).toBe(options[0].range.startCharacter);
    decorations.dispose();
  });

  it("still marks ambiguous and failing elements", () => {
    mocks.decorate.mockClear();
    mocks.styles.length = 0;
    const decorations = create(
      entry("found"),
      entry("ambiguous", { diagnostic: { matchCount: 3 } }),
      entry("error"),
    );
    const decorated = mocks.decorate.mock.calls.filter(([, options]) => options.length);
    expect(decorated.map(([, options]) => options[0].renderOptions.after.contentText)).toEqual([
      "  \u26a0 3 matches",
      "  \u2717 error",
    ]);
    decorations.dispose();
  });
});
