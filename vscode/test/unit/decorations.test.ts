import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  decorate: vi.fn(),
  styles: [] as unknown[],
}));
vi.mock("vscode", () => ({
  languages: { createDiagnosticCollection: () => ({ clear: vi.fn(), dispose: vi.fn() }) },
  Uri: { joinPath: vi.fn() },
  ThemeColor: class {},
  Range: class {},
  window: {
    visibleTextEditors: [{ document: { uri: { fsPath: "c:\\demo\\pages\\main.py" } }, setDecorations: mocks.decorate }],
    createTextEditorDecorationType: () => {
      const style = { dispose: vi.fn() };
      mocks.styles.push(style);
      return style;
    },
    onDidChangeVisibleTextEditors: () => ({ dispose: vi.fn() }),
  },
}));
import { CheckDecorations } from "../../src/editor/decorations";

describe("Windows backend editor paths", () => {
  it("decorates a native lowercase-drive document for a POSIX backend path", () => {
    let refresh = () => {};
    const decorations = new CheckDecorations({
      entries: new Map([["element", {
        page: { file: "C:/demo/pages/main.py" },
        element: { range: { start: { line: 4 } } },
        result: { status: "found" },
      }]]),
      onDidChange: (listener: () => void) => { refresh = listener; return { dispose: vi.fn() }; },
    } as never, {} as never);
    refresh();
    expect(mocks.decorate).toHaveBeenCalledWith(mocks.styles[0], [expect.objectContaining({
      renderOptions: { after: { contentText: "  \u2713 found" } },
    })]);
    decorations.dispose();
  });
});
