import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { DiscoveryStore } from "../../src/discovery/store";

const mocks = vi.hoisted(() => ({
  commands: new Map<string, (value: unknown) => Promise<void>>(),
  register: vi.fn(),
  definitions: vi.fn(),
  read: vi.fn(),
  show: vi.fn(),
  dispose: vi.fn(),
  error: vi.fn(),
  nameAt: vi.fn(),
  byName: vi.fn(),
  trusted: true,
  enabled: true,
}));
vi.mock("vscode", () => ({
  languages: { registerHoverProvider: mocks.register },
  commands: {
    executeCommand: mocks.definitions,
    registerCommand: (name: string, handler: (value: unknown) => Promise<void>) => {
      mocks.commands.set(name, handler);
      return { dispose() {} };
    },
  },
  workspace: { get isTrusted() { return mocks.trusted; } },
  window: { showErrorMessage: mocks.error },
  Uri: { file: (fsPath: string) => ({ fsPath }) },
  MarkdownString: class {
    value = "";
    appendText(text: string) { this.value += text; return this; }
    appendMarkdown(text: string) { this.value += text; return this; }
  },
  Hover: class {
    constructor(public contents: unknown, public range: unknown) {}
  },
}));
vi.mock("../../src/spy/objectPreviews", () => ({ readObjectPreview: mocks.read }));
vi.mock("../../src/spy/previewViewer", () => ({
  PreviewViewer: class {
    show = mocks.show;
    dispose = mocks.dispose;
  },
}));
import { ElementPreviews } from "../../src/editor/elementPreviews";

const file = "C:/project/pages/Login.py";
const located = {
  project: { root: { fsPath: "C:/project", toString: () => "file:///C:/project" } },
  page: { file },
  element: { id: "pages/Login.py::Login.submit", qualname: "Login.submit", kind: "element" },
};
const position = { line: 3, character: 5 } as vscode.Position;
const range = { start: position, end: { line: 3, character: 11 } };
const document = {
  uri: { fsPath: file },
  getWordRangeAtPosition: () => range,
  getText: () => "submit",
} as unknown as vscode.TextDocument;
const preview = {
  width: 640, height: 200,
  cropDataUrl: "data:image/webp;base64,AAAA",
  windowDataUrl: "data:image/webp;base64,BBBB",
  capturedAt: "2026-10-23T09:10:11+00:00",
};
let provider: ElementPreviews;
let cancellation: vscode.CancellationToken;
const content = (hover: vscode.Hover | undefined) => hover?.contents as unknown as {
  value: string; supportHtml?: boolean; isTrusted?: { enabledCommands: string[] };
};
const hover = () => provider.provideHover(document, position, cancellation);

beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(preview.capturedAt) + 25 * 60000);
  mocks.commands.clear();
  mocks.trusted = true;
  mocks.enabled = true;
  mocks.register.mockReturnValue({ dispose() {} });
  mocks.definitions.mockResolvedValue([]);
  mocks.nameAt.mockReturnValue(located);
  mocks.byName.mockReturnValue(located);
  mocks.read.mockResolvedValue(preview);
  cancellation = { isCancellationRequested: false } as vscode.CancellationToken;
  provider = new ElementPreviews({
    elementNameAt: mocks.nameAt, elementByName: mocks.byName,
  } as unknown as DiscoveryStore, { error: mocks.error } as unknown as vscode.LogOutputChannel, () => mocks.enabled);
});
afterEach(() => {
  provider.dispose();
  vi.restoreAllMocks();
});

describe("element capture hovers", () => {
  it("registers only for Python files", () => {
    expect(mocks.register).toHaveBeenCalledWith({ language: "python", scheme: "file" }, provider);
  });
  it("shows the bounded crop, check timestamp and explicit open links without any RPC", async () => {
    const result = content(await hover());
    expect(result.value).toContain("Login.submit");
    expect(result.value).toContain('width="320" height="100"');
    expect(result.value).toContain(preview.cropDataUrl);
    expect(result.value).not.toContain(preview.windowDataUrl);
    expect(result.value).toContain("Captured by Check Element 25 minutes ago.");
    expect(result.value).toContain("Not a live image");
    expect(result.value).toContain("Open full image");
    expect(result.value).toContain("Show app context");
    expect(result.isTrusted).toEqual({ enabledCommands: ["wintestkit.openElementCapture"] });
    expect(mocks.read).toHaveBeenCalledWith("C:/project", located.element.id);
    expect(mocks.definitions).not.toHaveBeenCalled();
    expect(mocks.show).not.toHaveBeenCalled();
  });
  it("does not upscale small captures", async () => {
    mocks.read.mockResolvedValue({ ...preview, width: 20, height: 10 });
    expect(content(await hover()).value).toContain('width="20" height="10"');
  });
  it.each([
    [0, "just now"],
    [59999, "just now"],
    [60000, "1 minute ago"],
    [25 * 60000, "25 minutes ago"],
    [3599999, "59 minutes ago"],
    [3600000, "1 hour ago"],
    [25 * 3600000, "1 day ago"],
    [49 * 3600000, "2 days ago"],
    [-60000, "just now"],
  ])("shows capture age for %i milliseconds as %s", async (elapsed, label) => {
    vi.mocked(Date.now).mockReturnValue(Date.parse(preview.capturedAt) + elapsed);
    const result = content(await hover()).value;
    expect(result).toContain("Captured by Check Element " + label + ".");
    expect(result).not.toContain(preview.capturedAt);
  });
  it("bounds tall captures", async () => {
    mocks.read.mockResolvedValue({ ...preview, width: 200, height: 1000 });
    expect(content(await hover()).value).toContain('width="40" height="200"');
  });
  it("explains how to create a missing capture without creating one", async () => {
    mocks.read.mockResolvedValue(undefined);
    const result = content(await hover());
    expect(result.value).toContain("Check exists CodeLens");
    expect(result.value).not.toContain("<img");
    expect(result.isTrusted).toBeUndefined();
  });
  it("handles invalid or unreadable captures without failing the hover", async () => {
    mocks.read.mockRejectedValue(new Error("Unsafe saved preview path"));
    expect(content(await hover()).value).toContain("Saved capture unavailable");
    expect(mocks.error).toHaveBeenCalled();
  });
  it.each(["window", "elements"])("does not advertise captures for %s definitions", async (kind) => {
    mocks.nameAt.mockReturnValue({ ...located, element: { ...located.element, kind } });
    expect(await hover()).toBeUndefined();
    expect(mocks.read).not.toHaveBeenCalled();
  });
  it("resolves an element reference through the Python definition provider", async () => {
    mocks.nameAt.mockReturnValueOnce(undefined).mockReturnValueOnce(located);
    mocks.definitions.mockResolvedValue([{ targetUri: { fsPath: file }, targetSelectionRange: range }]);
    expect(content(await hover()).value).toContain(preview.cropDataUrl);
    expect(mocks.definitions).toHaveBeenCalledWith("vscode.executeDefinitionProvider", document.uri, position);
  });
  it("ignores a failed definition lookup without reading captures", async () => {
    mocks.nameAt.mockReturnValue(undefined);
    mocks.definitions.mockRejectedValue(new Error("Provider unavailable"));
    expect(await hover()).toBeUndefined();
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.error).toHaveBeenCalled();
  });
  it.each(["disabled", "untrusted", "cancelled"])("stops when %s during definition lookup", async (state) => {
    mocks.nameAt.mockReturnValueOnce(undefined).mockReturnValueOnce(located);
    mocks.definitions.mockImplementation(async () => {
      if (state === "disabled") mocks.enabled = false;
      if (state === "untrusted") mocks.trusted = false;
      if (state === "cancelled") Object.assign(cancellation, { isCancellationRequested: true });
      return [{ uri: { fsPath: file }, range }];
    });
    expect(await hover()).toBeUndefined();
    expect(mocks.read).not.toHaveBeenCalled();
  });
  it("supports Location results as well as LocationLink results", async () => {
    mocks.nameAt.mockReturnValueOnce(undefined).mockReturnValueOnce(located);
    mocks.definitions.mockResolvedValue([{ uri: { fsPath: file }, range }]);
    expect(content(await hover()).value).toContain(preview.cropDataUrl);
  });
  it("does not guess when a reference resolves to multiple elements", async () => {
    mocks.nameAt.mockReturnValueOnce(undefined).mockReturnValueOnce(located).mockReturnValueOnce({
      ...located, element: { ...located.element, id: "pages/Other.py::Other.submit" },
    });
    mocks.definitions.mockResolvedValue([{ uri: {}, range }, { uri: {}, range }]);
    expect(await hover()).toBeUndefined();
    expect(mocks.read).not.toHaveBeenCalled();
  });
  it("does not show an image for an unrelated symbol", async () => {
    mocks.nameAt.mockReturnValue(undefined);
    expect(await hover()).toBeUndefined();
    expect(mocks.read).not.toHaveBeenCalled();
  });
  it.each(["disabled", "untrusted", "cancelled"])("does no work when %s", async (state) => {
    if (state === "disabled") mocks.enabled = false;
    if (state === "untrusted") mocks.trusted = false;
    if (state === "cancelled") cancellation = { isCancellationRequested: true } as vscode.CancellationToken;
    expect(await hover()).toBeUndefined();
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.definitions).not.toHaveBeenCalled();
  });
  it("honors cancellation while reading a capture", async () => {
    mocks.read.mockImplementation(async () => {
      Object.assign(cancellation, { isCancellationRequested: true });
      return preview;
    });
    expect(await hover()).toBeUndefined();
  });
  it("rereads the capture so successful later checks are immediately visible", async () => {
    await hover();
    mocks.read.mockResolvedValue({ ...preview, capturedAt: new Date(Date.now() - 60000).toISOString() });
    expect(content(await hover()).value).toContain("Captured by Check Element 1 minute ago.");
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });
  it.each(["element", "window"])("opens the validated %s image from a hover link", async (view) => {
    const markdown = content(await hover()).value;
    const links = [...markdown.matchAll(/command:wintestkit\.openElementCapture\?([^)]*)/g)];
    const target = JSON.parse(decodeURIComponent(links[view === "element" ? 0 : 1][1]))[0];
    await mocks.commands.get("wintestkit.openElementCapture")?.(target);
    expect(mocks.byName).toHaveBeenCalledWith({ fsPath: file }, "Login.submit");
    expect(mocks.show).toHaveBeenCalledWith(view, view === "element" ? preview.cropDataUrl : preview.windowDataUrl);
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });
  it.each([null, {}, { file, qualname: "Login.submit", view: "invalid" }])("rejects malformed open arguments %#", async (target) => {
    await mocks.commands.get("wintestkit.openElementCapture")?.(target);
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.show).not.toHaveBeenCalled();
  });
  it("rejects open arguments outside discovered elements", async () => {
    mocks.byName.mockReturnValue(undefined);
    await mocks.commands.get("wintestkit.openElementCapture")?.({ file: "C:/outside.py", qualname: "Login.submit", view: "element" });
    expect(mocks.read).not.toHaveBeenCalled();
  });
  it("disposes the temporary image viewer", () => {
    provider.dispose();
    expect(mocks.dispose).toHaveBeenCalled();
  });
});
