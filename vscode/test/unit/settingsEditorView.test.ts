import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { describe, expect, it } from "vitest";
import { settingFields, settingSections } from "../../src/settings/model";

const script = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../media/settings/editor.js",
  ),
  "utf8",
);

interface Focus {
  current: DomNode | null;
}

class DomNode {
  tagName: string;
  className = "";
  textContent = "";
  value = "";
  type = "";
  disabled = false;
  checked = false;
  placeholder = "";
  title = "";
  open = false;
  htmlFor = "";
  min = "";
  step = "";
  spellcheck = true;
  parent: DomNode | null = null;
  children: DomNode[] = [];
  attrs: Record<string, string> = {};
  onclick: (() => void) | null = null;
  onchange: (() => void) | null = null;
  ontoggle: (() => void) | null = null;
  private idValue = "";

  constructor(
    tag: string,
    private readonly selection: Focus,
  ) {
    this.tagName = tag.toUpperCase();
    this.append = (...kids: DomNode[]) => {
      for (const kid of kids) {
        kid.parent = this;
        this.children.push(kid);
      }
    };
    this.replaceChildren = (...kids: DomNode[]) => {
      this.children = [];
      this.append(...kids);
    };
    this.setAttribute = (name: string, value: string) => {
      this.attrs[name] = String(value);
    };
    this.getAttribute = (name: string) => {
      if (name === "id") return this.idValue;
      return this.attrs[name] ?? null;
    };
    this.focus = () => {
      if (!this.disabled) this.selection.current = this;
    };
    this.click = () => {
      this.onclick?.();
    };
    this.querySelector = (selector: string) => {
      const match = /^\[id='([^']*)'\]$/.exec(selector);
      if (!match) throw new Error("Unsupported selector " + selector);
      const want = match[1];
      const stack = [...this.children];
      while (stack.length) {
        const node = stack.shift();
        if (!node) break;
        if (node.idValue === want) return node;
        stack.push(...node.children);
      }
      return null;
    };
  }

  get id() {
    return this.idValue;
  }

  set id(value: string) {
    this.idValue = String(value);
  }

  append: (...kids: DomNode[]) => void;
  replaceChildren: (...kids: DomNode[]) => void;
  setAttribute: (name: string, value: string) => void;
  getAttribute: (name: string) => string | null;
  focus: () => void;
  click: () => void;
  querySelector: (selector: string) => DomNode | null;
}

function findNode(
  node: DomNode,
  predicate: (node: DomNode) => boolean,
): DomNode | null {
  if (predicate(node)) return node;
  for (const child of node.children) {
    const found = findNode(child, predicate);
    if (found) return found;
  }
  return null;
}

interface SavedState {
  advancedOpen?: boolean;
  marker?: string;
}

function boot(saved?: SavedState) {
  const selection: Focus = { current: null };
  const posts: unknown[] = [];
  const listeners: ((event: { data: unknown }) => void)[] = [];
  const root = new DomNode("div", selection);
  const stored: { current: SavedState | undefined } = { current: saved };
  for (const id of [
    "local",
    "shared",
    "source",
    "save",
    "project",
    "scope",
    "status",
    "fields",
  ]) {
    const node = new DomNode(id === "fields" ? "main" : "button", selection);
    node.id = id;
    root.append(node);
  }
  const document = {
    createElement: (tag: string) => new DomNode(tag, selection),
    getElementById: (id: string) => findNode(root, (node) => node.id === id),
    get activeElement() {
      return selection.current;
    },
  };
  vm.runInNewContext(
    script,
    {
      document,
      window: {
        addEventListener: (
          type: string,
          listener: (event: { data: unknown }) => void,
        ) => {
          if (type === "message") listeners.push(listener);
        },
      },
      acquireVsCodeApi: () => ({
        postMessage: (message: unknown) => {
          posts.push(message);
        },
        getState: () => stored.current,
        setState: (next: SavedState) => {
          stored.current = next;
          return next;
        },
      }),
    },
    { filename: "editor.js" },
  );
  return {
    posts,
    document,
    emit(data: unknown) {
      for (const listener of listeners) listener({ data });
    },
    get(id: string) {
      return document.getElementById(id);
    },
    must(id: string) {
      const node = document.getElementById(id);
      if (!node) throw new Error("Missing #" + id);
      return node;
    },
    find(predicate: (node: DomNode) => boolean) {
      return findNode(root, predicate);
    },
    saved: () => stored.current,
  };
}

function effective(extra: Record<string, unknown> = {}) {
  const values: Record<string, unknown> = {};
  for (const field of settingFields)
    if (field.default !== undefined) values[field.key] = field.default;
  return { ...values, ...extra };
}

function state(
  scope: "local" | "shared",
  version: number,
  values: Record<string, unknown>,
  extra: Record<string, unknown> = {},
) {
  return {
    type: "state",
    scope,
    name: "calculator-tests",
    version,
    dirty: true,
    sections: settingSections(scope),
    values,
    effective: effective(extra),
  };
}

function changes(posts: unknown[]) {
  return posts.filter(
    (message): message is { type: string; [key: string]: unknown } =>
      !!message &&
      typeof message === "object" &&
      "type" in message &&
      message.type === "change",
  );
}

describe("settings editor script", () => {
  it("clears an explicit executable and leaves an inherited path alone", () => {
    const view = boot();
    expect(view.posts[0]).toEqual({ type: "ready" });
    view.emit(
      state("local", 4, { "app.path": "C:\\Apps\\Demo.exe" }, {
        "app.path": "C:\\Apps\\Demo.exe",
      }),
    );
    const input = view.must("app.path");
    expect(input.value).toBe("C:\\Apps\\Demo.exe");
    expect(view.must("app.path-meta").textContent).toContain("Set in this file");
    expect(view.get("app.path-override")).toBeNull();
    input.value = "   ";
    input.onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      type: "change",
      version: 4,
      key: "app.path",
      remove: true,
    });
    view.emit(
      state("local", 5, {}, { "app.path": "C:\\Inherited\\App.exe" }),
    );
    const inherited = view.must("app.path");
    expect(inherited.value).toBe("");
    expect(inherited.placeholder).toBe("C:\\Inherited\\App.exe");
    expect(view.must("app.path-meta").textContent).toContain(
      "Inherited: C:\\Inherited\\App.exe",
    );
    const count = view.posts.length;
    inherited.value = " ";
    inherited.onchange?.();
    expect(view.posts).toHaveLength(count);
    inherited.value = "D:\\New.exe";
    inherited.onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      version: 5,
      key: "app.path",
      value: "D:\\New.exe",
      remove: false,
    });
    view.must("app.path-browse").click();
    expect(view.posts.at(-1)).toEqual({ type: "browse" });
  });

  it("sends the viewed version and holds further edits until the host replies", () => {
    const view = boot();
    view.emit(state("local", 8, { "app.path": "C:\\Apps\\Demo.exe", timeout: 15 }));
    const input = view.must("app.path");
    input.value = "C:\\A.exe";
    input.onchange?.();
    const count = view.posts.length;
    view.must("timeout").value = "21";
    view.must("timeout").onchange?.();
    expect(view.posts).toHaveLength(count);
    view.emit({ type: "error", message: "Error: nope" });
    expect(view.must("status").className).toBe("error");
    expect(view.must("status").textContent).toBe("Error: nope");
    view.must("timeout").value = "21";
    view.must("timeout").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      version: 8,
      key: "timeout",
      value: 21,
      remove: false,
    });
    view.emit(state("local", 9, { timeout: 21 }, { timeout: 21 }));
    expect(view.must("status").className).toBe("");
    expect(view.must("status").textContent).toContain("Unsaved changes");
  });

  it("restores focus for dotted fields, browse, and the shared executable link", () => {
    const view = boot();
    view.emit(
      state("local", 2, {
        "app.path": "C:\\Apps\\Demo.exe",
        "app.startup_timeout": 12,
        launch: "attach",
      }),
    );
    view.must("app.startup_timeout").focus();
    view.emit(
      state("local", 3, {
        "app.path": "C:\\Apps\\Demo.exe",
        "app.startup_timeout": 12,
        launch: "attach",
      }),
    );
    expect(view.document.activeElement?.id).toBe("app.startup_timeout");
    expect(view.must("app.startup_timeout").disabled).toBe(false);
    view.must("launch-override").focus();
    view.emit(
      state("local", 4, {
        "app.path": "C:\\Apps\\Demo.exe",
        "app.startup_timeout": 12,
        launch: "attach",
      }),
    );
    expect(view.document.activeElement?.id).toBe("launch-override");
    const browse = view.must("app.path-browse");
    expect(browse.getAttribute("aria-label")).toBe(
      "Browse for Application executable",
    );
    browse.focus();
    view.emit(
      state("local", 5, {
        "app.path": "C:\\Apps\\Demo.exe",
        "app.startup_timeout": 12,
        launch: "attach",
      }),
    );
    expect(view.document.activeElement?.id).toBe("app.path-browse");
    view.emit(state("shared", 6, { "app.process": "Shared.exe" }));
    const edit = view.must("local-executable");
    expect(edit.textContent).toContain("Set the executable");
    edit.focus();
    view.emit(state("shared", 7, { "app.process": "Shared.exe" }));
    expect(view.document.activeElement?.id).toBe("local-executable");
    view.document.activeElement?.click();
    expect(view.posts.at(-1)).toEqual({ type: "scope", scope: "local" });
  });

  it("remembers whether advanced options are open", () => {
    const closed = boot();
    closed.emit(state("local", 1, {}));
    const details = closed.find((node) => node.tagName === "DETAILS");
    if (!details?.ontoggle) throw new Error("Missing advanced details");
    expect(details.open).toBe(false);
    details.open = true;
    details.ontoggle();
    expect(closed.saved()).toEqual({ advancedOpen: true });
    closed.emit(state("local", 2, { timeout: 15 }));
    expect(closed.find((node) => node.tagName === "DETAILS")?.open).toBe(true);

    const opened = boot({ advancedOpen: true, marker: "keep" });
    opened.emit(state("local", 1, {}));
    const restored = opened.find((node) => node.tagName === "DETAILS");
    if (!restored?.ontoggle) throw new Error("Missing advanced details");
    expect(restored.open).toBe(true);
    restored.open = false;
    restored.ontoggle();
    expect(opened.saved()).toEqual({ advancedOpen: false, marker: "keep" });
    opened.emit(state("local", 2, {}));
    expect(opened.find((node) => node.tagName === "DETAILS")?.open).toBe(false);
  });

  it("overrides advanced values without dropping inherited or shared scope", () => {
    const view = boot();
    view.emit(state("local", 3, { timeout: 15 }));
    expect(view.must("app.process-meta").textContent).toContain("Not set");
    const count = view.posts.length;
    const process = view.must("app.process-override");
    process.checked = true;
    process.onchange?.();
    expect(view.posts).toHaveLength(count);
    expect(view.document.activeElement?.id).toBe("app.process");
    view.must("launch-override").checked = true;
    view.must("launch-override").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "launch",
      value: "per-test",
      remove: false,
      version: 3,
    });
    view.emit({ type: "error", message: "Error: pause" });
    view.must("slow_mo_ms-override").checked = true;
    view.must("slow_mo_ms-override").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "slow_mo_ms",
      value: 0,
      remove: false,
    });
    expect(typeof changes(view.posts).at(-1)?.value).toBe("number");
    view.emit({ type: "error", message: "Error: pause" });
    view.must("highlight_actions-override").checked = true;
    view.must("highlight_actions-override").onchange?.();
    expect(changes(view.posts).at(-1)?.value).toBe(false);
    view.emit({ type: "error", message: "Error: pause" });
    view.must("python_paths-override").checked = true;
    view.must("python_paths-override").onchange?.();
    expect(changes(view.posts).at(-1)?.value).toEqual(["."]);
    view.emit({ type: "error", message: "Error: pause" });
    view.must("python_paths").value = "{";
    view.must("python_paths").onchange?.();
    expect(view.must("status").textContent).toContain("SyntaxError");
    view.must("python_paths-override").checked = false;
    view.must("python_paths-override").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "python_paths",
      remove: true,
    });
    view.emit({ type: "error", message: "Error: pause" });
    view.must("timeout-override").checked = false;
    view.must("timeout-override").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "timeout",
      remove: true,
      version: 3,
    });
    view.emit(state("shared", 4, {}));
    expect(view.get("app.path")).toBeNull();
    expect(view.get("app.args")).toBeNull();
    expect(view.get("app.cwd")).toBeNull();
    expect(view.get("highlight_actions")).toBeNull();
    expect(view.get("slow_mo_ms")).toBeNull();
    expect(view.get("app.path-browse")).toBeNull();
    expect(view.must("timeout").disabled).toBe(true);
    expect(view.must("app.process").value).toBe("");
    expect(
      view.find(
        (node) => node.tagName === "H3" && node.textContent === "Debugging",
      ),
    ).toBeNull();
    expect(
      view.find((node) => node.textContent.includes("wintestkit.local.yaml")),
    ).not.toBeNull();
    view.must("source").click();
    expect(view.posts.at(-1)).toEqual({ type: "source" });
    view.must("save").click();
    expect(view.posts.at(-1)).toEqual({ type: "save" });
    view.must("shared").click();
    expect(view.posts.at(-1)).toEqual({ type: "scope", scope: "shared" });
  });
});
