import vm from "node:vm";
import { describe, expect, it } from "vitest";
import {
  NavigationSession,
  reduceNavigation,
  type NavNode,
} from "../../src/views/navigationModel";
import {
  navigationDocument,
  renderBody,
} from "../../src/views/navigationDocument";

const nodes: NavNode[] = [
  {
    id: "parent",
    label: "Parent",
    description: "",
    tooltip: "Parent",
    icon: "symbol-class",
    context: { webviewSection: "page", preventDefaultContextMenuItems: true },
    actions: [],
    children: [
      {
        id: "child",
        label: "Child",
        description: "",
        tooltip: "Child",
        icon: "symbol-field",
        context: {
          webviewSection: "element",
          preventDefaultContextMenuItems: true,
        },
        actions: [],
        children: [],
      },
    ],
  },
  {
    id: "other",
    label: "Other",
    description: "",
    tooltip: "Other",
    icon: "symbol-class",
    context: { webviewSection: "page", preventDefaultContextMenuItems: true },
    actions: [],
    children: [],
  },
];

function body(expanded: ReadonlySet<string>, focusId?: string): string {
  return renderBody({
    nodes,
    expanded,
    focusId,
    showInitialize: false,
  });
}

function tabindex(html: string, id: string): string | undefined {
  return new RegExp(`data-id="${id}"[^>]*tabindex="(-?\\d+)"`).exec(html)?.[1];
}

describe("navigation toggle focus", () => {
  it("selects the toggled row when a chevron expands or collapses it", () => {
    const session = new NavigationSession("pages");
    session.focus.flows = "stay";
    session.focus.pages = "other";
    expect(
      reduceNavigation(session, nodes, { type: "toggle", id: "parent" }, 1),
    ).toEqual({ type: "render" });
    expect(session.expanded.pages.has("parent")).toBe(true);
    expect(session.focus.pages).toBe("parent");
    expect(session.focus.flows).toBe("stay");
    const expanded = body(session.expanded.pages, session.focus.pages);
    expect(tabindex(expanded, "parent")).toBe("0");
    expect(tabindex(expanded, "child")).toBe("-1");
    expect(tabindex(expanded, "other")).toBe("-1");

    session.focus.pages = "child";
    expect(
      reduceNavigation(session, nodes, { type: "toggle", id: "parent" }, 2),
    ).toEqual({ type: "render" });
    expect(session.expanded.pages.has("parent")).toBe(false);
    expect(session.focus.pages).toBe("parent");
    const collapsed = body(session.expanded.pages, session.focus.pages);
    expect(tabindex(collapsed, "parent")).toBe("0");
    expect(collapsed).not.toContain('data-id="child"');
  });

  it("leaves focus unchanged when the toggle does not open a row", () => {
    const session = new NavigationSession("pages");
    session.focus.pages = "other";
    expect(
      reduceNavigation(session, nodes, { type: "toggle", id: "child" }, 1),
    ).toBeUndefined();
    expect(
      reduceNavigation(session, nodes, { type: "toggle", id: "missing" }, 1),
    ).toBeUndefined();
    expect(session.focus.pages).toBe("other");
    expect(session.expanded.pages.size).toBe(0);
  });
});

describe("navigation keyboard reveal", () => {
  it("marks tree key changes as reveals and leaves other renders passive", () => {
    const session = new NavigationSession("pages");
    expect(
      reduceNavigation(session, nodes, { type: "key", key: "End" }, 1),
    ).toEqual({ type: "render", reveal: true });
    expect(session.focus.pages).toBe("other");
    expect(
      reduceNavigation(session, nodes, { type: "key", key: "Home" }, 2),
    ).toEqual({ type: "render", reveal: true });
    expect(session.focus.pages).toBe("parent");
    expect(
      reduceNavigation(session, nodes, { type: "key", key: "ArrowDown" }, 3),
    ).toEqual({ type: "render", reveal: true });
    expect(session.focus.pages).toBe("other");
    expect(
      reduceNavigation(session, nodes, { type: "key", key: "p" }, 4),
    ).toEqual({ type: "render", reveal: true });
    expect(session.focus.pages).toBe("parent");
    expect(
      reduceNavigation(session, nodes, { type: "key", key: "ArrowUp" }, 5),
    ).toBeUndefined();
    expect(
      reduceNavigation(session, nodes, { type: "key", key: "Enter" }, 6),
    ).toEqual({ type: "render", openId: "parent", reveal: true });
    expect(reduceNavigation(session, nodes, { type: "ready" }, 7)).toEqual({
      type: "render",
    });
    expect(
      reduceNavigation(session, nodes, { type: "select", section: "flows" }, 8),
    ).toEqual({ type: "render" });
  });
});

class Dom {
  parent: Dom | null = null;
  children: Dom[] = [];
  attrs: Record<string, string> = {};
  tabIndex = -1;
  scrollTop = 0;
  clientHeight = 0;
  tag = "";
  listeners: Record<string, Array<(event: DomEvent) => void>> = {};
  constructor(readonly id = "") {}
  getAttribute(name: string): string | null {
    return this.attrs[name] ?? null;
  }
  setAttribute(name: string, value: string): void {
    this.attrs[name] = value;
    if (name === "tabindex") this.tabIndex = Number(value);
  }
  append(child: Dom): void {
    child.parent = this;
    this.children.push(child);
  }
  contains(node: Dom | null): boolean {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parent;
    }
    return false;
  }
  matches(selector: string): boolean {
    const parts = selector.match(/\[[^\]]+\]/g);
    if (!parts || parts.join("") !== selector) return false;
    return parts.every((part) => {
      const named = /^\[([^\]=]+)\]$/.exec(part);
      if (named) return this.getAttribute(named[1]) !== null;
      const exact = /^\[([^\]=]+)='([^']*)'\]$/.exec(part);
      return exact !== null && this.getAttribute(exact[1]) === exact[2];
    });
  }
  querySelectorAll(selector: string): Dom[] {
    const matches: Dom[] = [];
    const visit = (node: Dom) => {
      if (node.matches(selector)) matches.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return matches;
  }
  querySelector(selector: string): Dom | null {
    return this.querySelectorAll(selector)[0] ?? null;
  }
  closest(selector: string): Dom | null {
    if (this.matches(selector)) return this;
    return this.parent ? this.parent.closest(selector) : null;
  }
  get firstElementChild(): Dom | null {
    return this.children[0] ?? null;
  }
  enclosingTree(): Dom | null {
    if (this.id === "tree") return this;
    return this.parent ? this.parent.enclosingTree() : null;
  }
  getBoundingClientRect(): {
    top: number;
    bottom: number;
    left: number;
    right: number;
    width: number;
    height: number;
  } {
    const empty = { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 };
    const root = this.enclosingTree();
    if (!root) return empty;
    if (this === root) {
      const height = this.clientHeight;
      return { top: 0, bottom: height, left: 0, right: 0, width: 0, height };
    }
    const row =
      this.getAttribute("role") === "treeitem"
        ? this
        : this.closest("[role='treeitem']");
    if (!row) return empty;
    const rows = root.querySelectorAll("[role='treeitem']");
    const index = rows.indexOf(row);
    if (index < 0) return empty;
    const top = index * 22 - root.scrollTop;
    const height =
      this === row
        ? (1 + row.querySelectorAll("[role='treeitem']").length) * 22
        : 22;
    return { top, bottom: top + height, left: 0, right: 0, width: 0, height };
  }
  focus(options?: { preventScroll?: boolean }): void {
    focusLog.push({
      node: this,
      preventScroll: options?.preventScroll === true,
    });
    active.current = this;
  }
  addEventListener(type: string, listener: (event: DomEvent) => void): void {
    (this.listeners[type] ??= []).push(listener);
  }
  set innerHTML(html: string) {
    this.scrollTop = 0;
    this.children = [];
    if (!html) return;
    const stack: Dom[] = [this];
    const tags =
      /<!--[\s\S]*?-->|<\/([A-Za-z][\w:-]*)>|<([A-Za-z][\w:-]*)([^>]*?)(\/?)>/g;
    let match: RegExpExecArray | null;
    while ((match = tags.exec(html))) {
      if (match[0].startsWith("<!--")) continue;
      if (match[1]) {
        const name = match[1].toLowerCase();
        while (stack.length > 1 && stack[stack.length - 1].tag !== name)
          stack.pop();
        if (stack.length > 1) stack.pop();
        continue;
      }
      const el = new HTMLElement();
      el.tag = match[2].toLowerCase();
      let attrs = (match[3] ?? "").trim();
      if (attrs.endsWith("/")) attrs = attrs.slice(0, -1).trim();
      for (const attr of attrs.matchAll(
        /([^\s=/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'))?/g,
      )) {
        el.setAttribute(
          attr[1].toLowerCase(),
          decode(attr[2] ?? attr[3] ?? ""),
        );
      }
      stack[stack.length - 1].append(el);
      if (match[4] !== "/") stack.push(el);
    }
  }
}

interface DomEvent {
  target?: Dom;
  key?: string;
  preventDefault: () => void;
}

class Element extends Dom {}
class HTMLElement extends Element {}

const active: { current: Dom | null } = { current: null };
const focusLog: Array<{ node: Dom; preventScroll: boolean }> = [];
const webviewFocused = { current: true };

function decode(value: string): string {
  return value
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function navigationScript(): string {
  const html = navigationDocument({
    cspSource: "vscode-resource:",
    nonce: "n",
    iconsHref: "https://icons/codicon.css",
    section: "pages",
    treeHtml: "",
  });
  const script = /<script nonce="n">([\s\S]*)<\/script>/.exec(html)?.[1];
  if (!script) throw new Error("missing navigation script");
  return script;
}

function bootClient() {
  active.current = null;
  focusLog.length = 0;
  webviewFocused.current = true;
  const posts: unknown[] = [];
  const listeners: Array<(event: { data: unknown }) => void> = [];
  const segments = new HTMLElement("segments");
  const tree = new HTMLElement("tree");
  const tabs: Record<string, HTMLElement> = {};
  for (const section of ["pages", "flows"]) {
    const tab = new HTMLElement("tab-" + section);
    tab.setAttribute("data-section", section);
    tab.setAttribute("aria-selected", section === "pages" ? "true" : "false");
    tab.tabIndex = section === "pages" ? 0 : -1;
    segments.append(tab);
    tabs[section] = tab;
  }
  vm.runInNewContext(
    navigationScript(),
    {
      document: {
        getElementById: (id: string) =>
          id === "segments" ? segments : id === "tree" ? tree : null,
        get activeElement() {
          return active.current;
        },
        hasFocus: () => webviewFocused.current,
      },
      window: {
        addEventListener: (
          type: string,
          listener: (event: { data: unknown }) => void,
        ) => {
          if (type === "message") listeners.push(listener);
        },
      },
      acquireVsCodeApi: () => ({
        postMessage: (message: unknown) => posts.push(message),
      }),
      Element,
      HTMLElement,
    },
    { filename: "navigation.js" },
  );
  return {
    posts,
    tabs,
    tree,
    focusLog,
    webviewFocused,
    active: () => active.current,
    paint(section: string, html: string, reveal = false) {
      for (const listener of listeners)
        listener({
          data: reveal
            ? { type: "render", section, html, reveal: true }
            : { type: "render", section, html },
        });
    },
    press(key: string) {
      const event = { key, preventDefault() {} };
      for (const listener of tree.listeners.keydown ?? []) listener(event);
    },
    click(target: Dom) {
      for (const listener of tree.listeners.click ?? [])
        listener({ target, preventDefault() {} });
    },
    row(id: string) {
      const row = tree
        .querySelectorAll("[role='treeitem']")
        .find((node) => node.getAttribute("data-id") === id);
      if (!row) throw new Error("Missing row " + id);
      return row;
    },
  };
}

describe("navigation document focus", () => {
  it("keeps the expanded row focused after a chevron click repaint", () => {
    const client = bootClient();
    expect(client.posts[0]).toEqual({ type: "ready" });
    const session = new NavigationSession("pages");
    session.focus.pages = "other";
    client.paint("pages", body(session.expanded.pages, session.focus.pages));
    const twist = client.row("parent").querySelector("[data-twist]");
    const icon = twist?.children[0];
    if (!twist || !icon) throw new Error("missing chevron");
    icon.focus();
    client.click(icon);
    expect(client.posts.at(-1)).toEqual({ type: "toggle", id: "parent" });
    expect(
      reduceNavigation(
        session,
        nodes,
        client.posts.at(-1) as { type: "toggle"; id: string },
        3,
      ),
    ).toEqual({ type: "render" });
    client.focusLog.length = 0;
    client.tree.scrollTop = 80;
    client.paint("pages", body(session.expanded.pages, session.focus.pages));
    expect(client.active()?.getAttribute("data-id")).toBe("parent");
    expect(client.focusLog).toEqual([
      { node: client.active(), preventScroll: true },
    ]);
    expect(client.row("other").getAttribute("tabindex")).toBe("-1");
    expect(client.tree.tabIndex).toBe(-1);
    expect(client.tree.scrollTop).toBe(80);
  });

  it("restores a focused row without scrolling and keeps scroll on every paint", () => {
    const client = bootClient();
    const html = body(new Set(["parent"]), "parent");
    client.paint("pages", html);
    client.row("parent").focus();
    client.focusLog.length = 0;
    client.tree.scrollTop = 9;
    client.paint("pages", html);
    expect(client.active()?.getAttribute("data-id")).toBe("parent");
    expect(client.focusLog).toEqual([
      { node: client.active(), preventScroll: true },
    ]);
    expect(client.tree.scrollTop).toBe(9);
    expect(client.tree.tabIndex).toBe(-1);
  });

  it("focuses the tree when the webview is focused and no row can take focus", () => {
    const client = bootClient();
    const html = body(new Set(), undefined);
    client.paint("pages", html);
    const twist = client.row("parent").querySelector("[data-twist]");
    if (!twist) throw new Error("missing chevron");
    twist.focus();
    client.focusLog.length = 0;
    client.tree.scrollTop = 64;
    client.paint("pages", html);
    expect(client.tree.querySelector("[role='treeitem']")).not.toBeNull();
    expect(
      client.tree.querySelector("[role='treeitem'][tabindex='0']"),
    ).toBeNull();
    expect(client.active()).toBe(client.tree);
    expect(client.focusLog).toEqual([
      { node: client.tree, preventScroll: true },
    ]);
    expect(client.tree.tabIndex).toBe(0);
    expect(client.tree.scrollTop).toBe(64);
  });

  it("does not pull focus back from the editor after the webview blurs", () => {
    const client = bootClient();
    const selected = body(new Set(["parent"]), "parent");
    client.paint("pages", selected);
    client.row("parent").focus();
    client.tabs.pages.focus();
    client.focusLog.length = 0;
    client.webviewFocused.current = false;
    client.tree.scrollTop = 48;
    client.paint("flows", body(new Set(), "other"));
    expect(client.focusLog).toEqual([]);
    expect(client.active()).toBe(client.tabs.pages);
    expect(client.tabs.flows.getAttribute("aria-selected")).toBe("true");
    expect(client.row("other").getAttribute("tabindex")).toBe("0");
    expect(client.tree.scrollTop).toBe(48);

    client.row("other").focus();
    client.focusLog.length = 0;
    client.tree.scrollTop = 33;
    client.paint("pages", selected);
    expect(client.focusLog).toEqual([]);
    expect(client.active()?.getAttribute("data-id")).toBe("other");
    expect(client.row("parent").getAttribute("tabindex")).toBe("0");
    expect(client.tree.scrollTop).toBe(33);
  });

  it("moves a focused segment with preventScroll and leaves outside focus alone", () => {
    const client = bootClient();
    const outside = new HTMLElement("outside");
    client.tabs.pages.focus();
    client.focusLog.length = 0;
    client.tree.scrollTop = 17;
    client.paint("flows", body(new Set(["parent"]), "parent"));
    expect(client.active()).toBe(client.tabs.flows);
    expect(client.focusLog).toEqual([
      { node: client.tabs.flows, preventScroll: true },
    ]);
    expect(client.tree.scrollTop).toBe(17);
    expect(client.row("parent").getAttribute("tabindex")).toBe("0");

    outside.focus();
    client.focusLog.length = 0;
    client.tree.scrollTop = 11;
    client.paint("pages", "");
    expect(client.focusLog).toEqual([]);
    expect(client.active()).toBe(outside);
    expect(client.tabs.pages.getAttribute("aria-selected")).toBe("true");
    expect(client.tree.scrollTop).toBe(11);
  });

  it("scrolls keyboard navigation onto a row outside the viewport", () => {
    const client = bootClient();
    const session = new NavigationSession("pages");
    session.expanded.pages.add("parent");
    const expanded = session.expanded.pages;
    client.tree.clientHeight = 22;
    client.paint("pages", body(expanded));
    client.tree.focus();
    client.tree.scrollTop = 0;
    const move = (key: string, now: number) => {
      client.focusLog.length = 0;
      client.press(key);
      const message = client.posts.at(-1);
      expect(message).toEqual({ type: "key", key });
      expect(
        reduceNavigation(
          session,
          nodes,
          message as { type: "key"; key: string },
          now,
        ),
      ).toEqual({ type: "render", reveal: true });
      client.paint("pages", body(expanded, session.focus.pages), true);
    };

    move("End", 10);
    expect(session.focus.pages).toBe("other");
    expect(client.active()?.getAttribute("data-id")).toBe("other");
    expect(client.focusLog).toEqual([
      { node: client.active(), preventScroll: true },
    ]);
    expect(client.tree.scrollTop).toBe(44);

    move("Home", 20);
    expect(session.focus.pages).toBe("parent");
    expect(client.tree.scrollTop).toBe(0);
    client.paint("pages", body(expanded, "parent"), true);
    expect(client.tree.scrollTop).toBe(0);

    move("ArrowDown", 30);
    expect(session.focus.pages).toBe("child");
    expect(client.tree.scrollTop).toBe(22);

    move("o", 40);
    expect(session.focus.pages).toBe("other");
    expect(client.tree.scrollTop).toBe(44);

    client.tree.clientHeight = 66;
    move("Home", 800);
    expect(session.focus.pages).toBe("parent");
    expect(client.tree.scrollTop).toBe(0);
    move("ArrowDown", 810);
    expect(session.focus.pages).toBe("child");
    expect(client.tree.scrollTop).toBe(0);

    client.focusLog.length = 0;
    client.tree.clientHeight = 22;
    client.tree.scrollTop = 44;
    client.paint("pages", body(expanded, "child"));
    expect(client.active()?.getAttribute("data-id")).toBe("child");
    expect(client.focusLog).toEqual([
      { node: client.active(), preventScroll: true },
    ]);
    expect(client.tree.scrollTop).toBe(44);

    client.webviewFocused.current = false;
    client.focusLog.length = 0;
    client.tree.scrollTop = 15;
    client.paint("pages", body(expanded, "other"), true);
    expect(client.focusLog).toEqual([]);
    expect(client.active()?.getAttribute("data-id")).toBe("child");
    expect(client.tree.scrollTop).toBe(15);
  });
});

describe("leaf rows under a page", () => {
  it("marks only rows without children as leaves", () => {
    const html = body(new Set(["parent"]));
    expect(html).toMatch(/class="item leaf"[^>]*data-id="child"/);
    expect(html).toMatch(/class="item page-item leaf"[^>]*data-id="other"/);
    expect(html).toMatch(/class="item page-item"[^>]*data-id="parent"/);
  });
  it("narrows the chevron gap only for nested leaves, not for root rows", () => {
    const css = /<style[^>]*>([\s\S]*?)<\/style>/.exec(
      navigationDocument({
        cspSource: "csp",
        nonce: "n",
        iconsHref: "codicon.css",
        section: "pages",
        treeHtml: "",
      }),
    )?.[1];
    expect(css).toContain(
      ".page-item .group > .item.leaf > .line > .spacer { width: 0; }",
    );
    expect(css).toContain(
      ".page-item .group > .item.leaf::before { width: 15px; }",
    );
    expect(css).not.toMatch(/#tree > \.page-item[^{]*\.spacer/);
    // The indent lives on the line, so the highlight covers it; padding on the row itself would
    // start the highlight further right than other rows do.
    expect(css).toContain(
      ".page-item .group > .item.leaf > .line { padding-left: 16px; }",
    );
    expect(css).not.toMatch(/\.item\.leaf\s*\{[^}]*padding/);
  });
});

describe("keyboard access to row actions", () => {
  it("moves focus to row actions with F2 and restores the tree row with Escape", () => {
    const html = navigationDocument({
      cspSource: "csp",
      nonce: "n",
      iconsHref: "codicon.css",
      section: "pages",
      treeHtml: "",
    });
    expect(html).toContain('event.key === "F2"');
    expect(html).toContain('action.tabIndex = 0');
    expect(html).toContain('event.key === "Escape"');
    expect(html).toContain('target.closest("[role=\'treeitem\']")?.focus()');
  });
});
