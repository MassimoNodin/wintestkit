import * as path from "node:path";
import type * as vscode from "vscode";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Projects } from "../../src/projects";
import type { ServerManager } from "../../src/server/serverManager";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  notifications: new Map<string, (value: unknown) => void>(),
  clipboard: vi.fn(),
  command: vi.fn(),
  information: vi.fn(() => Promise.resolve(undefined)),
  icons: vi.fn(() => Promise.resolve({} as Record<string, string>)),
}));
vi.mock("../../src/spy/appIcons", () => ({
  readApplicationIcons: mocks.icons,
}));
vi.mock("vscode", () => ({
  Uri: {
    joinPath: (uri: { fsPath: string }, ...parts: string[]) => ({
      fsPath: [uri.fsPath, ...parts].join("/"),
      toString() {
        return this.fsPath;
      },
    }),
  },
  window: {
    registerWebviewViewProvider: () => ({ dispose() {} }),
    onDidChangeActiveTextEditor: () => ({ dispose() {} }),
    showInformationMessage: mocks.information,
  },
  commands: {
    registerCommand: () => ({ dispose() {} }),
    executeCommand: mocks.command,
  },
  env: { clipboard: { writeText: mocks.clipboard } },
}));
import { SpyView } from "../../src/spy/spyView";
import { RpcError } from "../../src/server/jsonrpc";

describe("Spy view bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.notifications.clear();
  });
  const create = async () => {
    const project = {
      root: { fsPath: "C:/demo", toString: () => "demo" },
      name: "demo",
    };
    const notificationDisposals: string[] = [];
    const client = {
      request: mocks.request,
      onNotification: (name: string, callback: (value: unknown) => void) => {
        mocks.notifications.set(name, callback);
        return {
          dispose: () => {
            notificationDisposals.push(name);
            mocks.notifications.delete(name);
          },
        };
      },
    };
    const provider = new SpyView(
      {
        all: [project],
        onDidChange: () => ({ dispose() {} }),
      } as unknown as Projects,
      {
        get: () => Promise.resolve({ client }),
        onDidChange: () => ({ dispose() {} }),
      } as unknown as ServerManager,
      { fsPath: path.resolve(".") } as vscode.Uri,
      { error: vi.fn() } as unknown as vscode.LogOutputChannel,
    );
    let receive: (value: unknown) => void = () => {};
    let visibility: () => void = () => {};
    const sent: { type: string; [key: string]: unknown }[] = [];
    const webview = {
      html: "",
      options: {},
      cspSource: "vscode-resource:",
      asWebviewUri: (uri: vscode.Uri) => uri,
      postMessage: (message: { type: string }) => {
        sent.push(message);
        return Promise.resolve(true);
      },
      onDidReceiveMessage: (callback: (value: unknown) => void) => {
        receive = callback;
        return { dispose() {} };
      },
    };
    const view = {
      webview,
      visible: true,
      onDidChangeVisibility: (callback: () => void) => {
        visibility = callback;
        return { dispose() {} };
      },
      onDidDispose: () => ({ dispose() {} }),
    };
    await provider.resolveWebviewView(view as unknown as vscode.WebviewView);
    return {
      provider,
      sent,
      receive: (value: unknown) => receive(value),
      view,
      visibility: () => visibility(),
      notificationDisposals,
    };
  };
  it("uses a restrictive CSP, validates messages and copies text", async () => {
    const fixture = await create();
    expect(fixture.view.webview.html).toContain("default-src 'none'");
    expect(fixture.view.webview.html).toContain("img-src data:");
    expect(fixture.view.webview.html).not.toContain('id="loading"');
    expect(fixture.view.webview.html).toContain('id="tree-loading"');
    expect(fixture.view.webview.html).toContain('id="details-loading"');
    expect(fixture.view.webview.html).toContain('id="details-empty"');
    expect(fixture.view.webview.html).toMatch(
      /script-src 'nonce-[a-f0-9]{48}'/,
    );
    expect(fixture.view.webview.html).not.toContain("{{");
    fixture.receive({ type: "execute", command: "unsafe" });
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.receive({ type: "copy", text: "ok = Element()" });
    await vi.waitFor(() =>
      expect(mocks.clipboard).toHaveBeenCalledWith("ok = Element()"),
    );
    fixture.provider.dispose();
  });
  it("loads executable icons after roots and reports each refresh phase", async () => {
    const roots = [{ nodeId: "root", info: { processId: 123 } }];
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "app.status" ? { running: true } : roots),
    );
    mocks.icons.mockResolvedValueOnce({ "123": "data:image/png;base64,abcd" });
    const fixture = await create();
    await fixture.provider.refresh();
    expect(mocks.icons).toHaveBeenCalledWith([123]);
    expect(fixture.sent).toContainEqual({
      type: "rootIcons",
      icons: { "123": "data:image/png;base64,abcd" },
    });
    expect(
      fixture.sent.findIndex((message) => message.type === "roots"),
    ).toBeLessThan(
      fixture.sent.findIndex((message) => message.type === "rootIcons"),
    );
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(
      progress.some((message) => message.phase === "Loading application icons"),
    ).toBe(true);
    expect(progress.at(-1)).toMatchObject({
      done: true,
      completed: 4,
      total: 4,
    });
    expect(new Set(progress.map((message) => message.taskId)).size).toBe(1);
    fixture.provider.dispose();
  });
  it("cleans up loading progress when a request fails", async () => {
    mocks.request.mockRejectedValue(new Error("cannot connect"));
    const fixture = await create();
    fixture.receive({ type: "refresh" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "error")).toBe(
        true,
      ),
    );
    expect(
      fixture.sent.filter((message) => message.type === "progress").at(-1),
    ).toMatchObject({ done: true, failed: true, target: "tree" });
    fixture.provider.dispose();
  });
  it("does not resurrect failed progress when a parallel inspection phase finishes", async () => {
    let finishHighlight: (value: unknown) => void = () => {};
    mocks.request.mockImplementation((method: string) => {
      if (method === "inspect.properties")
        return Promise.reject(new Error("element gone"));
      if (method === "inspect.highlight")
        return new Promise((resolve) => {
          finishHighlight = resolve;
        });
      return Promise.resolve({});
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "control" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "error")).toBe(
        true,
      ),
    );
    const count = fixture.sent.filter(
      (message) => message.type === "progress",
    ).length;
    finishHighlight(undefined);
    await new Promise((resolve) => setTimeout(resolve, 10));
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(progress).toHaveLength(count);
    expect(progress.at(-1)).toMatchObject({
      done: true,
      failed: true,
      target: "details",
    });
    fixture.provider.dispose();
  });
  it("discards icon results from an obsolete refresh", async () => {
    let finishIcons: (value: Record<string, string>) => void = () => {};
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "app.status"
          ? { running: true }
          : [{ nodeId: "root", info: { processId: 123 } }],
      ),
    );
    mocks.icons.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishIcons = resolve;
        }),
    );
    mocks.icons.mockResolvedValueOnce({ "123": "data:image/png;base64,bmV3" });
    const fixture = await create();
    const first = fixture.provider.refresh();
    await vi.waitFor(() => expect(mocks.icons).toHaveBeenCalledTimes(1));
    await fixture.provider.refresh();
    finishIcons({ "123": "data:image/png;base64,b2xk" });
    await first;
    expect(
      fixture.sent.filter((message) => message.type === "rootIcons"),
    ).toEqual([
      { type: "rootIcons", icons: { "123": "data:image/png;base64,bmV3" } },
    ]);
    fixture.provider.dispose();
  });
  it("reports per-node expansion progress and completes after children arrive", async () => {
    mocks.request.mockResolvedValue([]);
    const fixture = await create();
    fixture.receive({ type: "expand", nodeId: "branch" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "children")).toBe(
        true,
      ),
    );
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(progress.at(-1)).toMatchObject({
      nodeId: "branch",
      target: "tree",
      failed: false,
      completed: 2,
      total: 2,
      done: true,
    });
    expect(
      progress.some((message) => message.phase === "Reading child controls"),
    ).toBe(true);
    fixture.provider.dispose();
  });
  it("scopes successful inspection progress to the selected-object pane", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "inspect.properties"
          ? { info: {}, properties: {} }
          : method === "suggest.locator"
            ? { helpers: [], code: "Element()" }
            : undefined,
      ),
    );
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "control" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(progress.every((message) => message.target === "details")).toBe(
      true,
    );
    expect(progress.at(-1)).toMatchObject({
      nodeId: "control",
      completed: 4,
      total: 4,
      done: true,
      failed: false,
    });
    fixture.provider.dispose();
  });
  it("refreshes roots, stops picking when hidden, and releases notifications", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "app.status" ? { running: true } : []),
    );
    const fixture = await create();
    fixture.receive({ type: "ready" });
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "roots")).toBe(
        true,
      ),
    );
    await vi.waitFor(() =>
      expect(
        fixture.sent.some(
          (message) => message.type === "state" && message.picking === true,
        ),
      ).toBe(true),
    );
    mocks.notifications.get("spy.cancelled")?.({});
    expect(fixture.sent.at(-1)?.picking).toBe(false);
    fixture.view.visible = false;
    fixture.visibility();
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("spy.stop"),
    );
    fixture.provider.dispose();
    expect(fixture.notificationDisposals).toHaveLength(3);
  });
  it("refreshes stale node handles instead of retaining a broken tree", async () => {
    mocks.request.mockImplementation((method: string) =>
      method === "inspect.children"
        ? Promise.reject(new RpcError(-32005, "gone"))
        : Promise.resolve(method === "app.status" ? { running: false } : []),
    );
    const fixture = await create();
    fixture.receive({ type: "expand", nodeId: "stale" });
    await vi.waitFor(() =>
      expect(fixture.sent).toContainEqual({
        type: "error",
        message: "The element is gone; refreshed.",
      }),
    );
    expect(fixture.sent.some((message) => message.type === "roots")).toBe(true);
    fixture.provider.dispose();
  });
});
