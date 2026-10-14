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
