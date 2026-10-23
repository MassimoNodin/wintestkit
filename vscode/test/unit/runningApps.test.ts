import { describe, expect, it, vi } from "vitest";

vi.mock("vscode", () => ({
  Uri: { parse: (value: string) => ({ uri: value }) },
  ThemeIcon: class {
    constructor(readonly id: string) {}
  },
  QuickPickItemKind: { Separator: -1, Default: 0 },
  window: {},
}));
vi.mock("../../src/spy/appIcons", () => ({ readApplicationIcons: vi.fn() }));

import { runningAppItems } from "../../src/settings/runningApps";

const processes = [
  { name: "ChatGPT.exe", pids: [22976], windowTitle: "ChatGPT" },
  { name: "explorer.exe", pids: [10, 11], windowTitle: "Temp - File Explorer" },
  { name: "TextInputHost.exe", pids: [7952], windowTitle: "" },
];

describe("runningAppItems", () => {
  it("groups applications with a window before background processes", () => {
    const items = runningAppItems(processes);
    expect(items.map((item) => item.label)).toEqual([
      "Windows",
      "ChatGPT",
      "Temp - File Explorer",
      "Background processes",
      "TextInputHost.exe",
    ]);
    expect(items[0]).toMatchObject({ kind: -1 });
    expect(items[3]).toMatchObject({ kind: -1 });
    expect(items[0]).not.toHaveProperty("process");
  });

  it("leads with the window title and keeps the process name to save", () => {
    const [, chat, explorer, , host] = runningAppItems(processes);
    expect(chat).toMatchObject({
      label: "ChatGPT",
      description: "ChatGPT.exe  ·  PID 22976",
      process: "ChatGPT.exe",
    });
    expect(explorer?.description).toBe("explorer.exe  ·  2 processes");
    expect(host).toMatchObject({
      label: "TextInputHost.exe",
      description: "PID 7952",
      process: "TextInputHost.exe",
    });
  });

  it("uses the application's icon, taking the first process that has one", () => {
    const items = runningAppItems(processes, {
      "11": "data:image/png;base64,AAAA",
    });
    expect(items[2]?.iconPath).toEqual({ uri: "data:image/png;base64,AAAA" });
    expect(items[1]?.iconPath).toMatchObject({ id: "window" });
  });

  it("puts the currently selected application first and says so", () => {
    const items = runningAppItems(processes, {}, ["explorer.EXE"]);
    expect(items.map((item) => item.label)).toEqual([
      "Current application",
      "Temp - File Explorer",
      "Windows",
      "ChatGPT",
      "Background processes",
      "TextInputHost.exe",
    ]);
    expect(items[1]).toMatchObject({
      process: "explorer.exe",
      description: "explorer.exe  ·  2 processes  ·  currently selected",
    });
    expect(items[3]?.description).not.toContain("currently selected");
  });

  it("adds no current group when the selected application is not running", () => {
    expect(runningAppItems(processes, {}, ["Gone.exe"])).toEqual(
      runningAppItems(processes),
    );
  });

  it("omits a heading with nothing under it", () => {
    expect(runningAppItems([processes[0]!]).map((item) => item.label)).toEqual([
      "Windows",
      "ChatGPT",
    ]);
    expect(runningAppItems([])).toEqual([]);
  });
});
