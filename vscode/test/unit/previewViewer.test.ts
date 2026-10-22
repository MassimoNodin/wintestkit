import { existsSync, readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  execute: vi.fn<(...args: unknown[]) => Promise<undefined>>(() => Promise.resolve(undefined)),
  closed: [] as Array<(event: { closed: Array<{ input: unknown }> }) => void>,
  disposeTabs: vi.fn(),
}));
vi.mock("vscode", () => ({
  Uri: { file: (fsPath: string) => ({ fsPath }) },
  ViewColumn: { Active: -1 },
  commands: { executeCommand: mocks.execute },
  window: {
    tabGroups: {
      onDidChangeTabs: (listener: (event: { closed: Array<{ input: unknown }> }) => void) => {
        mocks.closed.push(listener);
        return { dispose: mocks.disposeTabs };
      },
    },
  },
}));

import { PreviewViewer } from "../../src/spy/previewViewer";

const webp = "UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==";
const url = "data:image/webp;base64," + webp;
const openedFile = (call = -1) => (mocks.execute.mock.calls.at(call)?.[1] as { fsPath: string }).fsPath;

describe("PreviewViewer", () => {
  let viewer: PreviewViewer;
  beforeEach(() => {
    mocks.execute.mockClear();
    mocks.closed.length = 0;
    viewer = new PreviewViewer();
  });
  afterEach(() => viewer.dispose());

  it("writes the image to a temporary file and opens it in the built-in viewer", async () => {
    await viewer.show("window", url);
    const file = openedFile();
    expect(file).toMatch(/wintestkit-previews-[0-9a-f]+[\\/]wintestkit-window-1\.webp$/);
    expect(readFileSync(file)).toEqual(Buffer.from(webp, "base64"));
    expect(mocks.execute).toHaveBeenCalledWith("vscode.open", expect.anything(), { preview: true, viewColumn: -1 });
  });

  it.each([
    "https://example.test/a.webp", "data:image/png;base64," + webp, "data:image/webp;base64,not base64!",
    "data:image/webp;base64,AAAA", "data:image/webp;base64," + webp.slice(0, 20),
  ])("refuses %s without writing anything", async (value) => {
    await expect(viewer.show("element", value)).rejects.toThrow();
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it("deletes the file when its editor tab closes", async () => {
    await viewer.show("element", url);
    const file = openedFile();
    expect(existsSync(file)).toBe(true);
    mocks.closed[0]({ closed: [{ input: { uri: { fsPath: "C:/other/file.webp" } } }, { input: undefined }] });
    expect(existsSync(file)).toBe(true);
    mocks.closed[0]({ closed: [{ input: { uri: { fsPath: file } } }] });
    await vi.waitFor(() => expect(existsSync(file)).toBe(false));
  });

  it("keeps only the most recent images", async () => {
    const files: string[] = [];
    for (let index = 0; index < 10; index++) {
      await viewer.show("element", url);
      files.push(openedFile());
    }
    await vi.waitFor(() => expect(files.filter((file) => existsSync(file))).toEqual(files.slice(2)));
  });

  it("removes its whole folder when disposed", async () => {
    await viewer.show("window", url);
    const file = openedFile();
    viewer.dispose();
    expect(existsSync(file)).toBe(false);
    expect(mocks.disposeTabs).toHaveBeenCalled();
  });
});
