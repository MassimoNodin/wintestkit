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
  hidden = false;
  scrolled = 0;
  scrollIntoView() {
    this.scrolled++;
  }
  max = "";
  style = {
    props: {} as Record<string, string>,
    setProperty(name: string, value: string) {
      this.props[name] = value;
    },
  };
  parent: DomNode | null = null;
  children: DomNode[] = [];
  attrs: Record<string, string> = {};
  onclick: (() => void) | null = null;
  onchange: (() => void) | null = null;
  oninput: (() => void) | null = null;
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
    "project",
    "scope",
    "saving",
    "status",
    "fields",
  ]) {
    const node = new DomNode(id === "fields" ? "main" : "button", selection);
    node.id = id;
    root.append(node);
  }
  const document = {
    createElement: (tag: string) => new DomNode(tag, selection),
    createElementNS: (_namespace: string, tag: string) => new DomNode(tag, selection),
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
    fields: settingFields,
    sections: settingSections(scope),
    values,
    effective: effective(extra),
    inherited: effective(),
    repository: {},
    user: {},
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
    expect(view.must("status").hidden).toBe(true);
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
    view.must("launch-attach").focus();
    view.emit(
      state("local", 4, {
        "app.path": "C:\\Apps\\Demo.exe",
        "app.startup_timeout": 12,
        launch: "attach",
      }),
    );
    expect(view.document.activeElement?.id).toBe("launch-attach");
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
    view.emit(state("shared", 6, { "app.path": "bin/App.exe" }));
    expect(view.must("app.path").value).toBe("bin/App.exe");
    view.must("app.path-browse").focus();
    view.emit(state("shared", 7, { "app.path": "bin/App.exe" }));
    expect(view.document.activeElement?.id).toBe("app.path-browse");
    view.document.activeElement?.click();
    expect(view.posts.at(-1)).toEqual({ type: "browse" });
  });

  it("edits values in place", () => {
    const view = boot();
    view.emit(state("local", 3, { timeout: 15 }));
    const count = view.posts.length;
    const process = view.must("app.process");
    process.value = " ";
    process.onchange?.();
    expect(view.posts).toHaveLength(count);
    view.must("launch-attach").click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "launch",
      value: "attach",
      remove: false,
      version: 3,
    });
    view.emit({ type: "error", message: "Error: pause" });
    view.must("slow_mo_ms").value = "250";
    view.must("slow_mo_ms").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "slow_mo_ms",
      value: 250,
    });
    expect(typeof changes(view.posts).at(-1)?.value).toBe("number");
    view.emit({ type: "error", message: "Error: pause" });
    view.must("highlight_actions").click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "highlight_actions",
      value: true,
    });
    view.emit({ type: "error", message: "Error: pause" });
    view.must("python_paths").value = "{";
    view.must("python_paths").onchange?.();
    expect(view.must("status").textContent).toContain("SyntaxError");
    view.must("python_paths").value = '["src"]';
    view.must("python_paths").onchange?.();
    expect(changes(view.posts).at(-1)?.value).toEqual(["src"]);
    view.emit({ type: "error", message: "Error: pause" });
    view.emit(state("shared", 4, {}));
    expect(view.get("app.path")).not.toBeNull();
    expect(view.get("app.args")).not.toBeNull();
    expect(view.get("app.cwd")).toBeNull();
    expect(view.get("highlight_actions")).toBeNull();
    expect(view.get("slow_mo_ms")).toBeNull();
    expect(view.must("timeout").disabled).toBe(true);
    expect(view.must("timeout").value).toBe("");
    expect(view.must("app.process").value).toBe("");
    expect(
      view.find(
        (node) => node.tagName === "H3" && node.textContent === "Debugging",
      ),
    ).toBeNull();
    expect(view.must("scope").textContent).toContain("REPOSITORY SETTINGS");
    view.emit(state("local", 5, {}));
    expect(view.must("scope").textContent).toContain("USER SETTINGS");
    view.must("source").click();
    expect(view.posts.at(-1)).toEqual({ type: "source" });
    view.must("shared").click();
    expect(view.posts.at(-1)).toEqual({ type: "scope", scope: "shared" });
  });

  it("commits slider values only when released", () => {
    const view = boot();
    view.emit(state("local", 6, {}));
    const slider = view.must("slow_mo_ms-slider");
    slider.value = "1000";
    slider.oninput?.();
    expect(view.must("slow_mo_ms").value).toBe("1000");
    expect(changes(view.posts)).toHaveLength(0);
    slider.onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "slow_mo_ms",
      value: 1000,
      version: 6,
    });
  });

  it("saves both files automatically and has no Save button or changes block", () => {
    const view = boot();
    for (const scope of ["shared", "local"] as const) {
      view.emit({ ...state(scope, 2, { timeout: 15 }, { timeout: 15 }), dirty: false });
      expect(view.get("save")).toBeNull();
      expect(view.must("status").hidden).toBe(true);
      expect(
        view.find((node) => node.textContent === "Changes in this file"),
      ).toBeNull();
    }
    view.emit({ type: "error", message: "Error: nope" });
    expect(view.must("status").hidden).toBe(false);
  });

  it("shows every setting at once, with the executable inside Application", () => {
    const view = boot();
    view.emit(state("local", 1, {}));
    expect(view.find((node) => node.tagName === "DETAILS")).toBeNull();
    const application = view.find(
      (node) => node.tagName === "SECTION" && node.attrs["aria-labelledby"] === "group-application",
    );
    expect(application?.querySelector("[id='app.path']")).not.toBeNull();
    expect(application?.querySelector("[id='launch']")).not.toBeNull();
    for (const field of settingFields)
      expect(view.get(field.key)).not.toBeNull();
    const captured = (scope: string) =>
      view.find(
        (node) =>
          node.className === "option selected" && node.attrs["data-mode"] === scope,
      );
    expect(captured("window")).not.toBeNull();
    view.emit(state("local", 3, { replay_scope: "desktop" }));
    expect(captured("desktop")).not.toBeNull();
    view.emit(state("shared", 2, {}));
    const shared = view.find(
      (node) => node.tagName === "SECTION" && node.attrs["aria-labelledby"] === "group-application",
    );
    expect(shared?.querySelector("[id='app.path']")).not.toBeNull();
    expect(shared?.querySelector("[id='app.cwd']")).toBeNull();
  });

  describe("sharing captures in the repository", () => {
    const key = "object_previews_share";
    it("only offers a button to Repository Settings in User Settings", () => {
      const view = boot();
      view.emit(state("local", 90, {}));
      const button = view.must(key);
      expect(button.tagName).toBe("BUTTON");
      expect(button.attrs.role).toBeUndefined();
      expect(button.textContent).toBe("Open Repository Settings");
      expect(button.disabled).toBe(false);
      expect(view.get(key + "-enable")).toBeNull();
      button.click();
      expect(view.posts.at(-1)).toEqual({ type: "scope", scope: "shared", focus: key });
      view.emit({ ...state("local", 91, {}), repository: { [key]: true } });
      expect(view.find((node) => node.textContent.startsWith("Currently shared"))).not.toBeNull();
    });
    it("sends the open button to the setting and scrolls to it on arrival", () => {
      const view = boot();
      view.emit(state("local", 97, {}));
      view.must(key).click();
      expect(view.posts.at(-1)).toEqual({ type: "scope", scope: "shared", focus: key });
      view.emit({ ...state("shared", 98, { object_previews: true }), focus: key });
      const row = view.must(key + "-row") as unknown as { scrolled: number; className: string };
      expect(row.scrolled).toBe(1);
      expect(row.className).toContain("revealed");
      // A later refresh, without a focus, leaves the scroll position alone.
      view.emit(state("shared", 99, { object_previews: true }));
      expect((view.must(key + "-row") as unknown as { scrolled: number }).scrolled).toBe(0);
    });
    it("stays disabled in User Settings while capturing is off", () => {
      const view = boot();
      view.emit(state("local", 92, { object_previews: false }, { object_previews: false }));
      expect(view.must(key).disabled).toBe(true);
      expect(view.must(key + "-requires").textContent).toContain("first");
    });
    it("stays disabled in Repository Settings until captures are enabled there", () => {
      const view = boot();
      view.emit(state("shared", 93, {}));
      expect(view.must(key).disabled).toBe(true);
      expect(view.get(key + "-enable")).toBeNull();
      expect(view.must(key + "-requires").textContent).toBe(
        "Turn on “Save Check Element captures” first.",
      );
      view.emit(state("shared", 94, { object_previews: false }));
      expect(view.must(key).disabled).toBe(true);
      view.emit(state("shared", 95, { object_previews: true }));
      expect(view.get(key + "-requires")).toBeNull();
      // Captures are on: sharing can now be enabled for the repository like any other setting.
      expect(view.must(key + "-enable")).not.toBeNull();
      view.emit(state("shared", 96, { object_previews: true, [key]: true }, { [key]: true }));
      expect(view.must(key).disabled).toBe(false);
      view.must(key).click();
      expect(changes(view.posts).at(-1)).toMatchObject({ key, value: false, remove: false });
    });
  });

  it("picks the highlight color from swatches or a custom value and previews it", () => {
    const view = boot();
    view.emit(state("local", 7, {}));
    const outlined = () =>
      view.find((node) => node.className === "mini-button highlighted")?.style.props;
    expect(outlined()?.["--highlight"]).toBe("#FF0000");
    expect(view.must("highlight_color-red").getAttribute("aria-checked")).toBe("true");
    view.must("highlight_color-blue").click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "highlight_color",
      value: "#1E90FF",
      remove: false,
      version: 7,
    });
    view.emit({ type: "error", message: "Error: pause" });
    view.must("highlight_color").value = "#00ff7f";
    view.must("highlight_color").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({ value: "#00FF7F" });
    view.emit(
      state("local", 8, { highlight_color: "#AA00FF" }, { highlight_color: "#AA00FF" }),
    );
    expect(outlined()?.["--highlight"]).toBe("#AA00FF");
    expect(view.must("highlight_color-purple").getAttribute("aria-checked")).toBe("true");
    expect(view.must("highlight_color-red").getAttribute("aria-checked")).toBe("false");
    expect(view.must("highlight_color").value).toBe("#aa00ff");
    view.emit(state("shared", 9, {}));
    expect(view.get("highlight_color")).toBeNull();
  });

  it("covers a setting that uses the repository value with an Override button", () => {
    const view = boot();
    const tracked = (values: Record<string, unknown>) => ({
      ...state("local", 10, values, { timeout: 30, launch: "attach", slow_mo_ms: 0 }),
      repository: { timeout: 30, launch: "attach" },
    });
    view.emit(tracked({}));
    // Only settings the repository sets get a cover, and none has a tab while using the repository.
    expect(view.get("slow_mo_ms-override")).toBeNull();
    expect(view.get("highlight_color-override")).toBeNull();
    expect(view.get("timeout-repo")).toBeNull();
    expect(view.must("timeout").disabled).toBe(true);
    expect(view.must("timeout").value).toBe("30");
    expect(view.must("timeout-slider").disabled).toBe(true);
    expect(view.must("launch-attach").disabled).toBe(true);
    const cover = view.must("timeout-override");
    expect(cover.className).toBe("cover");
    expect(cover.title).toContain("using the repository value");
    expect(cover.getAttribute("aria-label")).toContain("Override Repository Setting");
    expect(cover.children.map((node) => node.tagName)).toEqual(["SPAN", "SVG"]);
    expect(cover.children[0].textContent).toBe("Override Repository Setting");
    expect(view.find((node) => node.className === "controls locked")).not.toBeNull();
    cover.click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "timeout",
      value: 30,
      remove: false,
      version: 10,
    });
    view.emit({ type: "error", message: "Error: pause" });
    // Overriding: editable, no cover, and a grey tab goes back to the repository value.
    view.emit(tracked({ timeout: 45 }));
    expect(view.get("timeout-override")).toBeNull();
    expect(view.must("timeout").disabled).toBe(false);
    expect(view.must("timeout").value).toBe("45");
    const tab = view.must("timeout-repo");
    expect(tab.className).toBe("repo-tab");
    expect(tab.title).toContain("Overriding the repository value");
    tab.click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "timeout",
      remove: true,
      version: 10,
    });
  });

  it("pre-fills list values and warns in Repository Settings when a setting is overridden", () => {
    const view = boot();
    view.emit({
      ...state("local", 11, {}),
      repository: { python_paths: ["src", "lib"] },
    });
    view.must("python_paths-override").click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "python_paths",
      value: ["src", "lib"],
    });
    view.emit({
      ...state("shared", 12, { timeout: 30, launch: "attach" }),
      user: { timeout: 5 },
    });
    expect(view.must("timeout-repo").className).toBe("repo-tab remove");
    const warning = view.must("timeout-warning");
    expect(warning.className).toBe("warning");
    expect(
      view.find((node) => node.textContent.includes("Overridden in your User Settings (5)")),
    ).not.toBeNull();
    expect(view.get("launch-warning")).toBeNull();
    expect(view.get("python_paths-warning")).toBeNull();
    view.must("timeout-open-user").click();
    expect(view.posts.at(-1)).toEqual({ type: "scope", scope: "local" });
  });

  it("enables repository settings one at a time from a blank, covered state", () => {
    const view = boot();
    view.emit({ ...state("shared", 20, { launch: "attach" }), user: { timeout: 5 } });
    // Unset: blank, disabled, covered by an enable button, and no tab.
    const timeout = view.must("timeout");
    expect(timeout.value).toBe("");
    expect(timeout.disabled).toBe(true);
    expect(view.must("timeout-slider").disabled).toBe(true);
    expect(view.get("timeout-repo")).toBeNull();
    expect(view.get("timeout-warning")).toBeNull();
    const cover = view.must("timeout-enable");
    expect(cover.className).toBe("cover");
    expect(cover.getAttribute("aria-label")).toContain("Enable Setting for Repository");
    expect(
      view.find((node) => node.parent === cover && node.textContent === "Enable Setting for Repository"),
    ).not.toBeNull();
    expect(view.must("input_mode-pattern").getAttribute("aria-checked")).toBe("false");
    expect(view.must("input_mode-mouse").getAttribute("aria-checked")).toBe("false");
    expect(view.must("input_mode-mouse").disabled).toBe(true);
    // Set: no cover, editable, showing its value, with a red tab that removes it.
    expect(view.get("launch-enable")).toBeNull();
    expect(view.must("launch-attach").getAttribute("aria-checked")).toBe("true");
    expect(view.must("launch-attach").disabled).toBe(false);
    expect(view.must("launch-repo").className).toBe("repo-tab remove");
    // Enabling a setting that has a default writes that default.
    cover.click();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "timeout",
      value: 10,
      remove: false,
      version: 20,
    });
    view.emit({ type: "error", message: "Error: pause" });
    view.must("python_paths-enable").click();
    expect(changes(view.posts).at(-1)).toMatchObject({ key: "python_paths", value: ["."] });
    view.emit({ type: "error", message: "Error: pause" });
    // The red tab removes a set setting from the file.
    view.must("launch-repo").click();
    expect(changes(view.posts).at(-1)).toMatchObject({ key: "launch", remove: true, version: 20 });
  });

  it("waits for a value when a repository setting has no default to write", () => {
    const view = boot();
    view.emit(state("shared", 30, {}));
    const posts = view.posts.length;
    expect(view.must("app.process").disabled).toBe(true);
    view.must("app.process-enable").click();
    expect(view.posts).toHaveLength(posts);
    expect(view.must("app.process").disabled).toBe(false);
    expect(view.must("app.process").value).toBe("");
    expect(view.get("app.process-enable")).toBeNull();
    expect(view.must("app.process-repo").className).toBe("repo-tab remove");
    expect(view.document.activeElement?.id).toBe("app.process");
    // Rows that were not enabled stay covered, and the draft survives a refresh.
    view.emit(state("shared", 31, {}));
    expect(view.must("app.process").disabled).toBe(false);
    expect(view.must("timeout").disabled).toBe(true);
    view.must("app.process").value = "Orders.exe";
    view.must("app.process").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({
      key: "app.process",
      value: "Orders.exe",
      version: 31,
    });
    // Removing a draft again does not touch the file and brings the cover back.
    view.emit(state("shared", 32, {}));
    view.must("app.path-enable").click();
    const before = view.posts.length;
    view.must("app.path-repo").click();
    expect(view.posts).toHaveLength(before);
    expect(view.must("app.path").disabled).toBe(true);
    expect(view.get("app.path-enable")).not.toBeNull();
    // Drafts do not carry over to the other file.
    view.must("app.path-enable").click();
    view.emit(state("local", 33, {}));
    view.emit(state("shared", 34, {}));
    expect(view.must("app.path").disabled).toBe(true);
  });

  it("shows a setting's diagram only while the setting is editable", () => {
    const view = boot();
    const diagram = () => view.find((node) => node.className === "compare");
    // Repository Settings: unset rows are covered, so no diagram until a row is enabled.
    view.emit(state("shared", 40, {}));
    expect(diagram()).toBeNull();
    view.must("input_mode-enable").click();
    view.emit(state("shared", 41, { input_mode: "mouse" }));
    expect(diagram()).not.toBeNull();
    // User Settings: no diagram while the repository value is in use, one once it is overridden.
    const tracked = (values: Record<string, unknown>) => ({
      ...state("local", 42, values),
      repository: { input_mode: "mouse", replay_scope: "desktop" },
    });
    view.emit(tracked({}));
    expect(diagram()).toBeNull();
    view.emit(tracked({ input_mode: "pattern" }));
    expect(diagram()).not.toBeNull();
    expect(view.find((node) => node.className === "tree")).toBeNull();
  });

  it("draws the Git logo as a single filled path", () => {
    const view = boot();
    view.emit({ ...state("shared", 43, { timeout: 30 }) });
    const tab = view.must("timeout-repo");
    const svg = tab.children[0];
    expect(svg.tagName).toBe("SVG");
    expect(svg.attrs.fill).toBe("currentColor");
    expect(svg.children).toHaveLength(1);
    expect(svg.children[0].tagName).toBe("PATH");
    expect(svg.children[0].attrs.d).toMatch(/^M23\.546 10\.93L13\.067\.452/);
  });

  it("switches a repository setting off when its value is left empty", () => {
    const view = boot();
    // Clearing a set text value removes it from the file.
    view.emit(state("shared", 50, { "app.process": "Orders.exe", timeout: 30 }));
    view.must("app.process").value = "  ";
    view.must("app.process").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({ key: "app.process", remove: true, version: 50 });
    view.emit({ type: "error", message: "Error: pause" });
    // Clearing a number is not an error in Repository Settings: it switches the setting off.
    view.must("timeout").value = "";
    view.must("timeout").onchange?.();
    expect(changes(view.posts).at(-1)).toMatchObject({ key: "timeout", remove: true, version: 50 });
    view.emit({ type: "error", message: "Error: pause" });
    // A value typed and then cleared in a freshly enabled row drops back to the cover.
    view.emit(state("shared", 51, {}));
    view.must("app.process-enable").click();
    expect(view.get("app.process-enable")).toBeNull();
    view.must("app.process").value = "x";
    view.must("app.process").value = "";
    view.must("app.process").onchange?.();
    expect(view.get("app.process-enable")).not.toBeNull();
    expect(view.must("app.process").disabled).toBe(true);
    // An enabled row left empty is switched off once focus has moved on.
    view.must("app.process-enable").click();
    expect(view.get("app.process-enable")).toBeNull();
    view.must("app.args-enable").focus();
    view.emit(state("shared", 52, {}));
    expect(view.get("app.process-enable")).not.toBeNull();
    // ...but stays enabled while it is still being edited.
    view.must("app.process-enable").click();
    view.emit(state("shared", 53, {}));
    expect(view.get("app.process-enable")).toBeNull();
    expect(view.must("app.process").disabled).toBe(false);
    // Enabling a second row without a default drops the first empty one.
    view.must("app.path-enable").focus();
    view.must("app.path-enable").click();
    expect(view.get("app.process-enable")).not.toBeNull();
    expect(view.get("app.path-enable")).toBeNull();
    // User Settings keep the old behaviour: clearing a number is an error, not a removal.
    view.emit(state("local", 54, { timeout: 15 }));
    view.must("timeout").value = "";
    view.must("timeout").onchange?.();
    expect(view.must("status").textContent).toContain("Enter a number");
  });

  it("shows a Saving spinner from an edit until the file is saved, not an unsaved banner", () => {
    const view = boot();
    view.emit({ ...state("local", 60, { timeout: 15 }), dirty: false });
    expect(view.must("saving").hidden).toBe(true);
    view.must("timeout").value = "20";
    view.must("timeout").onchange?.();
    expect(view.must("saving").hidden).toBe(false);
    // The edit lands and the file is dirty for a moment: still just "Saving".
    view.emit({ ...state("local", 61, { timeout: 20 }), dirty: true });
    expect(view.must("saving").hidden).toBe(false);
    expect(view.must("status").hidden).toBe(true);
    // Saved.
    view.emit({ ...state("local", 62, { timeout: 20 }), dirty: false });
    expect(view.must("saving").hidden).toBe(true);
    expect(view.must("status").hidden).toBe(true);
    // A failed save ends the spinner and shows the error.
    view.must("timeout").value = "25";
    view.must("timeout").onchange?.();
    expect(view.must("saving").hidden).toBe(false);
    view.emit({ type: "error", message: "Error: Configuration was not saved." });
    expect(view.must("saving").hidden).toBe(true);
    expect(view.must("status").hidden).toBe(false);
    expect(view.must("status").textContent).toContain("not saved");
    // An undo or redo is saved by the extension: the spinner is up from the moment it happens,
    // even before the file reports as dirty, and there is never an unsaved banner.
    view.emit({ ...state("local", 63, { timeout: 15 }), dirty: false, saving: true });
    expect(view.must("saving").hidden).toBe(false);
    expect(view.must("status").hidden).toBe(true);
    view.emit({ ...state("local", 64, { timeout: 15 }), dirty: true, saving: true });
    expect(view.must("saving").hidden).toBe(false);
    expect(view.must("status").hidden).toBe(true);
    view.emit({ ...state("local", 65, { timeout: 15 }), dirty: false });
    expect(view.must("saving").hidden).toBe(true);
    expect(view.must("status").hidden).toBe(true);
  });

  it("floats an error above the setting it is about, with a dismiss button", () => {
    const view = boot();
    view.emit(state("local", 80, { timeout: 15 }));
    const target = view.must("app.path") as unknown as {
      getBoundingClientRect: () => object;
    };
    target.getBoundingClientRect = () => ({ top: 300, bottom: 330, left: 500, right: 900 });
    view.must("app.path").value = "C:\\Elsewhere\\App.exe";
    view.must("app.path").onchange?.();
    view.emit({ type: "error", message: "Error: Choose an executable inside the project folder." });
    const status = view.must("status");
    expect(status.hidden).toBe(false);
    expect(status.className).toBe("error anchored");
    expect(status.style.props).toMatchObject({ top: "288px", left: "900px" });
    const dismiss = view.must("dismiss");
    expect(dismiss.getAttribute("aria-label")).toBe("Dismiss error");
    dismiss.onclick?.();
    expect(status.hidden).toBe(true);
  });

  it("puts an error below a setting too close to the top of the page", () => {
    const view = boot();
    view.emit(state("local", 81, { timeout: 15 }));
    const target = view.must("timeout") as unknown as {
      getBoundingClientRect: () => object;
    };
    target.getBoundingClientRect = () => ({ top: 20, bottom: 50, left: 500, right: 900 });
    view.must("timeout").value = "abc";
    view.must("timeout").onchange?.();
    expect(view.must("status").className).toBe("error anchored below");
    expect(view.must("status").style.props.top).toBe("62px");
  });

  it("keeps a text box red, with what was typed, until a change to it is saved", () => {
    const view = boot();
    view.emit({ ...state("local", 90, {}), effective: {} });
    view.must("app.path").value = "C:\\bad.exe";
    view.must("app.path").onchange?.();
    view.emit({ type: "error", message: "Error: nope", key: "app.path" });
    expect(view.must("app.path").className).toBe("invalid");
    expect(view.must("app.path").getAttribute("aria-invalid")).toBe("true");
    // Other changes redraw the page: the box stays red and keeps the text that was not saved.
    view.emit({ ...state("local", 91, { timeout: 20 }), effective: {} });
    expect(view.must("app.path").className).toBe("invalid");
    expect(view.must("app.path").value).toBe("C:\\bad.exe");
    expect(view.must("timeout").className).not.toBe("invalid");
    // A failed retry leaves it red.
    view.must("app.path").value = "C:\\still-bad.exe";
    view.must("app.path").onchange?.();
    view.emit({ type: "error", message: "Error: nope", key: "app.path" });
    expect(view.must("app.path").className).toBe("invalid");
    // A change that is saved clears it.
    view.must("app.path").value = "C:\\good.exe";
    view.must("app.path").onchange?.();
    view.emit({ type: "committed", key: "app.path" });
    view.emit({ ...state("local", 92, { "app.path": "C:\\good.exe" }), effective: {} });
    expect(view.must("app.path").className).toBe("");
    expect(view.must("app.path").value).toBe("C:\\good.exe");
  });

  it("marks a number that fails the page's own check, and ends when the box is emptied or saved", () => {
    const view = boot();
    view.emit(state("local", 93, { timeout: 15 }));
    view.must("timeout").value = "";
    view.must("timeout").onchange?.();
    expect(view.must("status").textContent).toContain("Enter a number");
    expect(view.must("timeout").className).toBe("invalid");
    // The Browse… failure case: an empty box that was never saved goes back to normal when emptied.
    view.emit({ ...state("local", 94, {}), effective: {} });
    view.emit({ type: "error", message: "Error: nope", key: "app.path" });
    expect(view.must("app.path").className).toBe("invalid");
    view.must("app.path").value = "";
    view.must("app.path").onchange?.();
    expect(view.must("app.path").className).toBe("");
    view.emit({ ...state("local", 95, {}), effective: {} });
    expect(view.must("app.path").className).toBe("");
  });

  it("forgets red boxes when switching between User and Repository Settings", () => {
    const view = boot();
    view.emit({ ...state("local", 96, {}), effective: {} });
    view.emit({ type: "error", message: "Error: nope", key: "app.path" });
    view.emit({ ...state("shared", 97, {}), effective: {} });
    expect(view.must("app.path").className).not.toBe("invalid");
  });

  it("floats an error about no setting at the top right", () => {
    const view = boot();
    view.emit(state("local", 82, { timeout: 15 }));
    view.emit({ type: "error", message: "Error: Open YAML to correct the file." });
    expect(view.must("status").className).toBe("error");
    expect(view.must("status").style.props).toMatchObject({ top: "", left: "" });
  });

  it("describes each setting for the file it is in", () => {
    const view = boot();
    view.emit(state("local", 83, {}));
    expect(view.must("app.path-description").textContent).toContain("on this machine");
    expect(view.must("timeout-description").textContent).toContain("slow");
    expect(view.must("input_mode-description").textContent).toBe(
      settingFields.find((field) => field.key === "input_mode")?.description.user,
    );
    view.emit(state("shared", 84, {}));
    expect(view.must("app.path-description").textContent).toContain("relative to the project folder");
    expect(view.must("timeout-description").textContent).toContain("before it fails");
    expect(view.must("input_mode-description").textContent).toBe(
      settingFields.find((field) => field.key === "input_mode")?.description.repository,
    );
  });

  it("warns about an absolute executable in Repository Settings only", () => {
    const view = boot();
    for (const absolute of ["C:\\Apps\\App.exe", "C:/Apps/App.exe", "\\\\host\\share\\App.exe", "/App.exe"]) {
      view.emit(state("shared", 87, { "app.path": absolute }));
      const warning = view.must("app.path-machine-warning");
      expect(warning.className).toBe("warning");
      expect(warning.textContent).toBe(
        "⚠ Only use an absolute path if the .exe will be installed in the same place on all machines.",
      );
      expect(view.must("app.path").getAttribute("aria-describedby")).toContain(
        "app.path-machine-warning",
      );
    }
    // A relative path, a setting that is not in the file, and User Settings get no warning.
    view.emit(state("shared", 88, { "app.path": "bin/Debug/App.exe" }));
    expect(view.get("app.path-machine-warning")).toBeNull();
    view.emit(state("shared", 89, {}));
    expect(view.get("app.path-machine-warning")).toBeNull();
    view.emit(state("local", 90, { "app.path": "C:\\Apps\\App.exe" }));
    expect(view.get("app.path-machine-warning")).toBeNull();
  });

  it("suggests an absolute path in User Settings and a relative one in Repository Settings", () => {
    const view = boot();
    view.emit({ ...state("local", 85, {}), effective: {} });
    expect(view.must("app.path").placeholder).toBe("C:\\Program Files\\Contoso\\Orders.exe");
    expect(view.must("app.process").placeholder).toBe("Orders.exe");
    view.emit({ ...state("shared", 86, {}), effective: {} });
    expect(view.must("app.path").placeholder).toBe("bin/Debug/Orders.exe");
    expect(view.must("app.process").placeholder).toBe("Orders.exe");
  });

  it("has no key and state caption under a setting", () => {
    const view = boot();
    for (const scope of ["local", "shared"] as const) {
      view.emit({ ...state(scope, 70, { timeout: 15 }), repository: { timeout: 30 } });
      expect(view.get("timeout-meta")).toBeNull();
      expect(view.find((node) => node.tagName === "SMALL")).toBeNull();
      expect(view.find((node) => /^app\.path · /.test(node.textContent))).toBeNull();
    }
  });

  it("marks only settings that differ from their baseline as modified in User Settings", () => {
    const view = boot();
    const modified = (key: string) =>
      view.find(
        (node) =>
          node.className.startsWith("setting") &&
          node.className.includes("modified") &&
          !!node.querySelector("[id='" + key + "']"),
      );
    // timeout differs from its default; the others are saved but equal to their defaults.
    view.emit(
      state("local", 80, {
        timeout: 15,
        launch: "per-test",
        input_mode: "pattern",
        object_previews: true,
        replay_scope: "window",
        highlight_color: "#ff0000",
      }),
    );
    expect(modified("timeout")).not.toBeNull();
    // The row carries the marker (an accent bar drawn by its class); nothing is added after the title.
    expect(view.must("timeout-label").textContent).toBe("Action / assertion timeout (seconds)");
    expect(view.get("timeout-reset")).toBeNull();
    expect(view.find((node) => node.className === "tag" || node.className === "heading")).toBeNull();
    for (const key of ["launch", "input_mode", "object_previews", "replay_scope", "highlight_color"])
      expect(modified(key)).toBeNull();
    // A value equal to the repository value (the baseline there) is not a change either.
    view.emit({
      ...state("local", 81, { timeout: 30, launch: "per-test" }),
      inherited: { ...effective(), timeout: 30, launch: "attach" },
      repository: { timeout: 30, launch: "attach" },
    });
    expect(modified("timeout")).toBeNull();
    expect(modified("launch")).not.toBeNull();
    // A setting with no baseline at all is modified once it has a value.
    view.emit(state("local", 82, { "app.process": "Orders.exe" }));
    expect(modified("app.process")).not.toBeNull();
    expect(view.find((node) => node.className.includes("overridden"))).toBeNull();
  });

  it("marks settings in Repository Settings that differ from their default, whatever User Settings override", () => {
    const view = boot();
    const modified = (key: string) =>
      view.find(
        (node) =>
          node.className.startsWith("setting") &&
          node.className.includes("modified") &&
          !!node.querySelector("[id='" + key + "']"),
      );
    // timeout (default 10) and app.process (no default) are modified; the rest equal their default.
    view.emit(
      state("shared", 83, {
        timeout: 15,
        launch: "per-test",
        input_mode: "pattern",
        "app.process": "Orders.exe",
      }),
    );
    expect(modified("timeout")).not.toBeNull();
    expect(modified("app.process")).not.toBeNull();
    expect(modified("launch")).toBeNull();
    expect(modified("input_mode")).toBeNull();
    // A setting that is not in the file is not modified, and a user override changes nothing here.
    expect(modified("replay_scope")).toBeNull();
    view.emit({
      ...state("shared", 84, { timeout: 10 }),
      user: { timeout: 99 },
      inherited: { ...effective(), timeout: 99 },
    });
    expect(modified("timeout")).toBeNull();
  });
});
