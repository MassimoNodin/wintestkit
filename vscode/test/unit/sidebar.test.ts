import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";

const mocks = vi.hoisted(() => ({
  registered: [] as Array<{ id: string; provider: unknown; options: unknown; dispose: () => void }>,
}));
vi.mock("vscode", () => ({
  Uri: {
    joinPath: (base: { fsPath: string }, ...parts: string[]) => ({
      fsPath: [base.fsPath, ...parts].join("/"),
    }),
  },
  window: {
    registerWebviewViewProvider: (id: string, provider: unknown, options: unknown) => {
      const entry = { id, provider, options, dispose: vi.fn() };
      mocks.registered.push(entry);
      return entry;
    },
  },
}));
import { sidebarDocument } from "../../src/views/sidebarDocument";
import { SIDEBAR_VIEW, SidebarView } from "../../src/views/sidebarView";

const page = {
  cspSource: "vscode-resource:",
  nonce: "abc",
  iconsHref: "https://icons/codicon.css",
  stylesHref: "https://media/setup.css",
  scriptHref: "https://media/setup.js",
  section: "pages" as const,
  treeHtml: "<div>$&</div>",
};

describe("sidebar page", () => {
  const html = sidebarDocument(page);
  it("puts Test Target above Pages & Flows, which stays hidden until Test Target shows it", () => {
    expect(html.indexOf('id="card"')).toBeLessThan(html.indexOf('id="pages"'));
    expect(html).toMatch(/<section id="pages"[^>]* hidden>/);
    expect(html.indexOf('id="segments"')).toBeGreaterThan(html.indexOf('id="pages"'));
    expect(html).toContain('id="tree" role="tree" aria-label="Page Tree"');
  });
  it("puts the tree in untouched, whatever it contains", () => {
    expect(html).toContain('id="setup-guide" aria-live="polite"');
    expect(html).toContain("<div>$&</div>");
  });
  it("keeps the instructions directly after the controls, ahead of notices and Pages & Flows", () => {
    expect(html).toMatch(/<main id="test-target">\s*<div id="card"[^>]*>[^]*?<\/div>\s*<aside id="setup-guide"[^>]*><\/aside>\s*<div id="target-notices"[^>]*><\/div>\s*<\/main>/);
    expect(html.indexOf('id="setup-guide"')).toBeLessThan(html.indexOf('id="pages"'));
  });
  it("allows only its own scripts and styles", () => {
    expect(html).toContain(
      "style-src vscode-resource: 'nonce-abc'; font-src vscode-resource:; script-src 'nonce-abc'",
    );
    expect(html).toContain("img-src data:");
    expect(html).toContain('<script nonce="abc" src="https://media/setup.js"></script>');
    expect(html).toContain('<link rel="stylesheet" href="https://media/setup.css" />');
  });
  it("runs the Pages & Flows script first, since it takes the page's one API handle", () => {
    const inline = html.indexOf('<script nonce="abc">');
    expect(inline).toBeGreaterThan(0);
    expect(inline).toBeLessThan(html.indexOf('src="https://media/setup.js"'));
    expect(html).toContain("window.vscodeApi ??= acquireVsCodeApi()");
    const target = readFileSync("media/setup/setup.js", "utf8");
    expect(target).toContain("window.vscodeApi ?? acquireVsCodeApi()");
    expect(target).not.toMatch(/^\s*const vscode = acquireVsCodeApi\(\)/m);
  });
});

describe("sidebar layout", () => {
  const css = readFileSync("media/setup/setup.css", "utf8");
  it("lets Test Target grow only until Pages & Flows is down to its minimum", () => {
    expect(css).toMatch(/--pages-min:\s*\d+px/);
    expect(css).toMatch(/#test-target\s*{[^}]*max-height:\s*max\(\d+px,\s*calc\(100% - var\(--pages-min\)\)\)[^}]*overflow-y:\s*auto/);
  });
  it("never shrinks Pages & Flows below that minimum", () => {
    expect(css).toMatch(/#pages\s*{[^}]*min-height:\s*var\(--pages-min\)/);
  });
  it("keeps Test Target usable when both sections need more height than the sidebar", () => {
    expect(css).toMatch(/#test-target\s*{[^}]*min-height:\s*120px/);
    expect(css).toMatch(/body\s*{[^}]*overflow-y:\s*auto/);
  });
  it("gives Test Target the whole sidebar when it is the only part", () => {
    expect(css).toMatch(/body\.solo #test-target\s*{[^}]*max-height:\s*none/);
  });
  it("dulls only Pages & Flows during the guide", () => {
    expect(css).toMatch(/#setup-guide:empty\s*{[^}]*display:\s*none/);
    expect(css).not.toMatch(/#setup-guide\s*{[^}]*position:\s*fixed/);
    expect(css).toMatch(/\.callout\s*{[^}]*overflow-y:\s*auto/);
    const html = sidebarDocument(page);
    expect(html).toContain("#pages.tour-dim::after");
    expect(html).not.toContain("body.tour-dim");
  });
});

describe("sidebar view", () => {
  function setup() {
    mocks.registered.length = 0;
    const target = { attach: vi.fn(), handleMessage: vi.fn() };
    const pages = {
      attach: vi.fn(),
      handleMessage: vi.fn(),
      initial: () => ({ section: "flows" as const, treeHtml: "<i>rows</i>" }),
    };
    const sidebar = new SidebarView(
      { fsPath: "C:/ext" } as vscode.Uri,
      target as never,
      pages as never,
    );
    let receive: (value: unknown) => void = () => {};
    const receiver = { dispose: vi.fn() };
    const webview = {
      cspSource: "vscode-resource:",
      options: {} as vscode.WebviewOptions,
      html: "",
      asWebviewUri: (uri: { fsPath: string }) => ({ toString: () => "https://x/" + uri.fsPath }),
      onDidReceiveMessage: (listener: (value: unknown) => void) => {
        receive = listener;
        return receiver;
      },
    };
    const view = { webview } as unknown as vscode.WebviewView;
    return { sidebar, target, pages, view, webview, receiver, send: (value: unknown) => receive(value) };
  }
  it("registers itself as the one view and keeps its page while hidden", () => {
    setup();
    expect(mocks.registered).toHaveLength(1);
    expect(mocks.registered[0].id).toBe(SIDEBAR_VIEW);
    expect(SIDEBAR_VIEW).toBe("wintestkit.sidebar");
    expect(mocks.registered[0].options).toEqual({ webviewOptions: { retainContextWhenHidden: true } });
  });
  it("builds the page from both parts and attaches them", () => {
    const { sidebar, target, pages, view, webview } = setup();
    sidebar.resolveWebviewView(view);
    expect(webview.options.enableScripts).toBe(true);
    expect(webview.options.localResourceRoots?.map((uri) => uri.fsPath)).toEqual([
      "C:/ext/media/setup",
      "C:/ext/media/codicons",
    ]);
    expect(webview.html).toContain('data-section="flows" aria-selected="true"');
    expect(webview.html).toContain("<i>rows</i>");
    expect(webview.html).toContain('href="https://x/C:/ext/media/setup/setup.css"');
    expect(webview.html).toContain('src="https://x/C:/ext/media/setup/setup.js"');
    expect(target.attach).toHaveBeenCalledWith(view);
    expect(pages.attach).toHaveBeenCalledWith(view);
  });
  it("lets both parts see every message, each ignoring what is not its own", () => {
    const { sidebar, target, pages, view, send } = setup();
    sidebar.resolveWebviewView(view);
    send({ type: "ready" });
    expect(target.handleMessage).toHaveBeenCalledWith({ type: "ready" });
    expect(pages.handleMessage).toHaveBeenCalledWith({ type: "ready" });
  });
  it("stops listening to a page it replaces and to everything on dispose", () => {
    const { sidebar, view, receiver } = setup();
    sidebar.resolveWebviewView(view);
    sidebar.resolveWebviewView(view);
    expect(receiver.dispose).toHaveBeenCalledOnce();
    sidebar.dispose();
    expect(receiver.dispose).toHaveBeenCalledTimes(2);
    expect(mocks.registered[0].dispose).toHaveBeenCalledOnce();
  });
});
