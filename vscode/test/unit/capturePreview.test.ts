import vm from "node:vm";
import { describe, expect, it } from "vitest";
import { CAPTURE_PREVIEW_MARKUP, CAPTURE_PREVIEW_SCRIPT, CAPTURE_PREVIEW_STYLE } from "../../src/views/capturePreviewDocument";
import { navigationMarkup } from "../../src/views/navigationDocument";

class ClientNode {
  hidden = false;
  disabled = false;
  textContent = "";
  title = "";
  alt = "";
  naturalWidth = 100;
  naturalHeight = 100;
  clientWidth = 200;
  clientHeight = 200;
  classes = new Set<string>();
  classList = { toggle: (name: string, enabled: boolean) => enabled ? this.classes.add(name) : this.classes.delete(name) };
  attrs: Record<string, string> = {};
  listeners = new Map<string, ((event: { data?: unknown }) => void)[]>();
  get src() { return this.attrs.src; }
  set src(value: string) { this.attrs.src = value; }
  getAttribute(name: string) { return this.attrs[name] ?? null; }
  setAttribute(name: string, value: string) { this.attrs[name] = value; }
  removeAttribute(name: string) { delete this.attrs[name]; }
  addEventListener(type: string, listener: (event: { data?: unknown }) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  emit(type: string, data?: unknown) {
    for (const listener of this.listeners.get(type) ?? []) listener({ data });
  }
}

function boot() {
  const nodes = new Map<string, ClientNode>();
  const get = (id: string) => {
    if (!nodes.has(id)) nodes.set(id, new ClientNode());
    return nodes.get(id)!;
  };
  const posts: { type: string; id: string; requestId?: number; view?: string }[] = [];
  const window = Object.assign(new ClientNode(), { vscodeApi: { postMessage: (message: typeof posts[number]) => posts.push(message) } });
  vm.runInNewContext(CAPTURE_PREVIEW_SCRIPT, { window, document: { getElementById: get } });
  return {
    get, posts,
    select(id?: string, section = "pages") {
      window.emit("message", { type: "render", section, html: "", captureSelection: id ? { id, qualname: "Main." + id } : undefined });
    },
    respond(capture?: unknown, request = posts.at(-1)) {
      window.emit("message", { ...request, capture });
    },
  };
}

const crop = "data:image/webp;base64,AAAA";
const app = "data:image/webp;base64,BBBB";
const saved = { image: crop, contextImage: app, message: "Captured 1 minute ago. Not a live image." };

describe("pinned capture preview", () => {
  it("places the preview after the tree without floating hover handlers", () => {
    const markup = navigationMarkup({ section: "pages", treeHtml: "" });
    expect(markup.indexOf('id="capture-preview"')).toBeGreaterThan(markup.indexOf('id="tree"'));
    expect(markup).toContain('</div></div>\n<section id="capture-preview"');
    expect(CAPTURE_PREVIEW_MARKUP).toContain("Select an element");
    expect(CAPTURE_PREVIEW_STYLE).not.toContain("position: fixed");
    expect(CAPTURE_PREVIEW_SCRIPT).not.toMatch(/mouseover|mouseenter|captureHover/);
  });
  it("distinguishes no selection, loading, and a selected element without a saved image", () => {
    const client = boot();
    client.select();
    expect(client.get("capture-empty").textContent).toContain("Select an element");
    expect(client.get("capture-open").disabled).toBe(true);
    expect(client.posts).toHaveLength(0);
    client.select("submit");
    expect(client.get("capture-empty").textContent).toContain("Loading");
    expect(client.get("capture-name").textContent).toBe("Main.submit");
    client.respond({ message: "No saved element capture." });
    expect(client.get("capture-empty").textContent).toContain("No saved check image for this element");
    expect(client.get("capture-image").hidden).toBe(true);
    expect(client.get("capture-element").disabled).toBe(true);
    expect(client.get("capture-context").disabled).toBe(true);
  });
  it("switches crop and context, opens the chosen image, and preserves the mode across selection", () => {
    const client = boot();
    client.select("submit");
    client.respond(saved);
    expect(client.get("capture-image").src).toBe(crop);
    expect(client.get("capture-message").textContent).toBe(saved.message);
    expect(client.get("capture-empty").hidden).toBe(true);
    client.get("capture-context").emit("click");
    expect(client.get("capture-image").src).toBe(app);
    expect(client.get("capture-context").getAttribute("aria-pressed")).toBe("true");
    client.get("capture-open").emit("click");
    expect(client.posts.at(-1)).toEqual({ type: "openCapture", id: "submit", view: "window" });
    client.select("cancel");
    expect(client.get("capture-image").src).toBeUndefined();
    client.respond(saved);
    expect(client.get("capture-image").src).toBe(app);
    client.get("capture-image").emit("click");
    expect(client.posts.at(-1)).toEqual({ type: "openCapture", id: "cancel", view: "window" });
  });
  it("ignores stale selection and refresh replies and clears on Flows or non-elements", () => {
    const client = boot();
    client.select("first");
    const first = client.posts.at(-1);
    client.select("second");
    const second = client.posts.at(-1);
    client.respond(saved, first);
    expect(client.get("capture-image").hidden).toBe(true);
    client.respond(saved, second);
    client.select("second");
    expect(client.get("capture-image").src).toBe(crop);
    client.respond({ image: app }, second);
    expect(client.get("capture-image").src).toBe(crop);
    client.respond({ image: app });
    expect(client.get("capture-image").src).toBe(app);
    client.select(undefined, "flows");
    expect(client.get("capture-image").hidden).toBe(true);
    expect(client.get("capture-name").hidden).toBe(true);
    client.respond(saved, first);
    expect(client.get("capture-image").hidden).toBe(true);
    client.select();
    expect(client.get("capture-empty").textContent).toContain("Select an element");
  });
  it("rejects unsafe URLs and handles missing replies and failed image loads", () => {
    const client = boot();
    client.select("submit");
    client.respond({ image: "https://example.com/private.png", contextImage: "javascript:alert(1)" });
    expect(client.get("capture-image").src).toBeUndefined();
    client.get("capture-open").emit("click");
    expect(client.posts).toHaveLength(1);
    client.respond();
    expect(client.get("capture-empty").textContent).toContain("No saved check image");
    client.respond(saved);
    client.get("capture-image").emit("error");
    expect(client.get("capture-empty").textContent).toContain("Saved image unavailable");
    expect(client.get("capture-image").hidden).toBe(true);
    expect(client.get("capture-open").disabled).toBe(true);
    client.get("capture-context").emit("click");
    expect(client.get("capture-image").src).toBe(app);
  });
  it("falls back to an available view and marks magnified captures", () => {
    const client = boot();
    client.select("submit");
    client.respond({ contextImage: app });
    expect(client.get("capture-image").src).toBe(app);
    expect(client.get("capture-element").disabled).toBe(true);
    client.get("capture-image").emit("load");
    expect(client.get("capture-image").classes.has("magnified")).toBe(true);
  });
  it("can run in minimal navigation hosts without a preview", () => {
    expect(() => vm.runInNewContext(CAPTURE_PREVIEW_SCRIPT, { document: { getElementById: () => null } })).not.toThrow();
  });
});
