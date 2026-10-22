import { readFileSync } from "node:fs";
import vm from "node:vm";
import { describe, expect, it } from "vitest";
import { buildTestAppModel } from "../../src/settings/testAppModel";

class Node {
  id = "";
  className = "";
  dataset: Record<string, string> = {};
  children: Node[] = [];
  inert = false;
  disabled = false;
  hidden = false;
  value = "";
  textContent = "";
  src = "";
  alt = "";
  scrollTop = 0;
  offsetWidth = 0;
  offsetHeight = 0;
  clientWidth = 900;
  rect?: { top: number; bottom: number; left: number; right: number };
  style: Record<string, unknown> & { values: Map<string, string>; setProperty: (name: string, value: string) => void } = {
    values: new Map<string, string>(),
    setProperty: (name: string, value: string) => { this.style.values.set(name, value); },
  };
  listeners: Record<string, () => void> = {};
  classList = {
    add: (...names: string[]) => {
      names.forEach((name) => this.classList.toggle(name, true));
    },
    remove: (...names: string[]) => {
      names.forEach((name) => this.classList.toggle(name, false));
    },
    contains: (name: string) => this.className.split(" ").includes(name),
    toggle: (name: string, enabled: boolean) => {
      const names = new Set(this.className.split(" ").filter(Boolean));
      if (enabled) names.add(name);
      else names.delete(name);
      this.className = [...names].join(" ");
    },
  };
  append(...nodes: Node[]) {
    this.children.push(...nodes);
  }
  replaceChildren() {
    this.children = [];
    this.scrollTop = 0;
  }
  setAttribute() {}
  addEventListener(type: string, callback: () => void) {
    this.listeners[type] = callback;
  }
  getBoundingClientRect() {
    return this.rect ?? {
      top: this.dataset.area ? 20 : 0,
      bottom: this.dataset.area ? 60 : 120,
      left: 0,
      right: 240,
    };
  }
  querySelectorAll(selector: string): Node[] {
    return this.children.flatMap((node) => [
      ...(selector === "[data-area]" && node.dataset.area ? [node] : []),
      ...node.querySelectorAll(selector),
    ]);
  }
  querySelector(selector: string): Node | undefined {
    return (
      this.children.find((node) =>
        node.classList.contains(selector.slice(1)),
      ) ??
      this.children.map((node) => node.querySelector(selector)).find(Boolean)
    );
  }
}

function client(file: "setup" | "spy", viewport: { width?: number } = {}) {
  const nodes = new Map<string, Node>();
  const element = (id: string) => {
    if (!nodes.has(id)) nodes.set(id, new Node());
    return nodes.get(id)!;
  };
  const body = new Node();
  let receive = (event: { data: unknown }) => {
    void event;
  };
  const posts: unknown[] = [];
  const captures = new Map<string, (event: unknown) => void>();
  const api = { postMessage(message: unknown) { posts.push(message); } };
  vm.runInNewContext(
    readFileSync("media/" + file + "/" + file + ".js", "utf8"),
    {
      document: {
        body,
        getElementById: element,
        createElement: () => new Node(),
        addEventListener: (type: string, listener: (event: unknown) => void) => captures.set(type, listener),
      },
      window: {
        innerHeight: 320,
        innerWidth: viewport.width,
        vscodeApi: api,
        addEventListener: (type: string, callback: typeof receive) => {
          if (type === "message") receive = callback;
        },
        matchMedia: () => ({ matches: false, addEventListener() {} }),
      },
      acquireVsCodeApi: () => api,
      requestAnimationFrame: (callback: () => void) => callback(),
    },
  );
  const dispatch = (type: string, id: string, key?: string, tutorial = false) => {
    let prevented = false;
    let stopped = false;
    captures.get(type)?.({
      type, key,
      target: { closest: () => tutorial ? element("extra-tutorial") : undefined },
      preventDefault: () => { prevented = true; },
      stopImmediatePropagation: () => { stopped = true; },
    });
    if (!stopped) element(id).listeners[type]?.();
    return { prevented, stopped };
  };
  return { body, element, posts, dispatch, send: (data: unknown) => receive({ data }) };
}

const tour = {
  phase: "setup",
  step: "package",
  kind: "todo",
  title: "Install WinTestKit",
  text: "Install the package",
  lit: ["interpreter"],
  panel: false,
  buttons: [],
  canBack: true,
  canNext: false,
};
const model = {
  kind: "app",
  tiles: [
    { id: "interpreter", title: "Python", codicon: "code" },
    { id: "app", title: "Application", codicon: "window" },
  ],
  tour,
};

describe("introduction clients", () => {
  it.each(["click", "dblclick", "auxclick", "pointerdown", "pointerup", "keydown", "beforeinput", "input", "change", "contextmenu", "dragstart", "drop"])("blocks %s outside the Spy tutorial without disabling the controls", (type) => {
    const spy = client("spy");
    const tutorial = { ...tour, phase: "extras", step: "spyPick", spyTarget: "pick" };
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    expect(spy.dispatch(type, "pick", "Enter")).toEqual({ prevented: true, stopped: true });
    expect(spy.element("pick").disabled).toBe(false);
    expect(spy.body.inert).toBe(false);
    expect(spy.element("pick").classList.contains("tutorial-spotlight")).toBe(true);
    expect(spy.dispatch(type, "", "Enter", true)).toEqual({ prevented: false, stopped: false });
    spy.send({ type: "tour", dim: false, spyLit: false });
    expect(spy.dispatch(type, "", "Enter")).toEqual({ prevented: false, stopped: false });
  });
  it("preserves hover, scrolling, and focus navigation in the read-only Spy tutorial", () => {
    const spy = client("spy");
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tour, phase: "extras" } });
    for (const type of ["mouseover", "pointerover", "mousemove", "wheel"])
      expect(spy.dispatch(type, "")).toEqual({ prevented: false, stopped: false });
    for (const key of ["Tab", "PageUp", "PageDown"])
      expect(spy.dispatch("keydown", "", key)).toEqual({ prevented: false, stopped: false });
    const before = spy.posts.length;
    spy.element("refresh").listeners.click();
    expect(spy.posts).toHaveLength(before);
    spy.send({ type: "tour", dim: false, spyLit: false });
    spy.dispatch("click", "refresh");
    expect(spy.posts.at(-1)).toEqual({ type: "refresh" });
  });
  it("hands the tutorial off from the sidebar to the Spy panel", () => {
    const sidebar = client("setup");
    const tutorial = { ...tour, step: "spy", phase: "extras", title: "Meet Spy", text: "Explore its features." };
    sidebar.send({ type: "model", model: { ...model, tour: tutorial } });
    const guide = sidebar.element("setup-guide");
    expect(guide.querySelector(".tutorial-handoff-arrow")?.textContent).toBe("↘");
    expect(guide.querySelector(".callout-title")?.textContent).toBe("Continue in WinTestKit Spy below");
    expect(sidebar.element("card").querySelectorAll("[data-area]").every((node) => !node.inert)).toBe(true);
    guide.querySelector(".secondary")?.listeners.click();
    expect(sidebar.posts.at(-1)).toEqual({ type: "tour", action: "openSpy" });
    const spy = client("spy");
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    expect(spy.element("extra-tutorial").hidden).toBe(false);
    expect(spy.element("extra-tutorial-body").querySelector(".tutorial-title")?.textContent).toBe("Meet Spy");
    expect(spy.element("extra-tutorial-body").querySelector(".tutorial-cancel")).toBeUndefined();
    expect(spy.element("extra-tutorial-body").querySelector(".tutorial-skip")).toBeUndefined();
    spy.send({ type: "tour", dim: false, spyLit: false });
    expect(spy.element("extra-tutorial").hidden).toBe(true);
  });

  it("keeps all four pick controls sharp and restores them on the next step", () => {
    const spy = client("spy");
    const tutorial = { ...tour, phase: "extras", step: "spyPick", spyTarget: "pick" };
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    for (const id of ["pick", "refresh", "collapse", "bring-front"]) {
      expect(spy.element(id).classList.contains("tutorial-spotlight")).toBe(true);
      expect(spy.dispatch("click", id)).toEqual({ prevented: true, stopped: true });
    }
    expect(spy.element("other-apps").classList.contains("tutorial-spotlight")).toBe(false);
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tutorial, step: "spyBrowse", spyTarget: "tree-pane" } });
    for (const id of ["pick", "refresh", "collapse", "bring-front"])
      expect(spy.element(id).classList.contains("tutorial-spotlight")).toBe(false);
  });

  it("highlights the selection summary and Highlight without lighting Properties", () => {
    const spy = client("spy");
    spy.send({ type: "selected", nodeId: "pane", properties: { info: { name: "VS Code", controlType: "Pane" }, properties: {} } });
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tour, phase: "extras", step: "spySelection", spyTarget: "selection-summary" } });
    for (const id of ["selection-summary", "highlight"])
      expect(spy.element(id).classList.contains("tutorial-spotlight")).toBe(true);
    expect(spy.element("properties-pane").classList.contains("tutorial-spotlight")).toBe(false);
    spy.send({ type: "tour", dim: false, spyLit: false });
    for (const id of ["selection-summary", "highlight"])
      expect(spy.element(id).classList.contains("tutorial-spotlight")).toBe(false);
  });

  it("outlines the visible definitions scroll area rather than its clipped contents", () => {
    const spy = client("spy", { width: 900 });
    spy.send({ type: "selected", nodeId: "pane", properties: { info: { name: "VS Code", controlType: "Pane" }, properties: {} } });
    spy.element("definitions-pane").rect = { top: 100, bottom: 170, left: 16, right: 351 };
    spy.element("definitions-group").rect = { top: 100, bottom: 184, left: 16, right: 341 };
    const guide = spy.element("extra-tutorial");
    guide.offsetWidth = 320;
    guide.offsetHeight = 150;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tour, phase: "extras", step: "spyDefinitions", spyTarget: "definitions-group" } });
    expect(spy.element("definitions-pane").classList.contains("tutorial-spotlight")).toBe(true);
    expect(spy.element("definitions-group").classList.contains("tutorial-spotlight")).toBe(false);
    expect(spy.element("locator-panel").classList.contains("tutorial-spotlight")).toBe(false);
    expect([guide.dataset.side, guide.style.left, guide.style.top]).toEqual(["right", "363px", "60px"]);
    spy.send({ type: "tour", dim: false, spyLit: false });
    expect(spy.element("definitions-pane").classList.contains("tutorial-spotlight")).toBe(false);
  });

  it("draws the Testing view's beaker SVG where the text names it", () => {
    const spy = client("spy");
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tour, phase: "extras", step: "test", text: "Open the Testing tab ($(beaker)) now." } });
    const icon = spy.element("extra-tutorial-body").querySelector(".tutorial-icon") as unknown as { innerHTML: string };
    expect(icon.innerHTML).toContain('<svg width="16" height="16" viewBox="0 0 16 16"');
    expect(icon.innerHTML).toContain("M12 0.998993C12.276");
    expect(icon.innerHTML).not.toContain("$(beaker)");
  });

  it("falls back to the inspector when definitions are hidden", () => {
    const spy = client("spy");
    spy.element("definitions-group").hidden = true;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tour, phase: "extras", step: "spyDefinitions", spyTarget: "definitions-group" } });
    expect(spy.element("details").classList.contains("tutorial-spotlight")).toBe(true);
    expect(spy.element("definitions-pane").classList.contains("tutorial-spotlight")).toBe(false);
  });

  it.each([400, 560, 900])("stacks narrow inspector columns at width %s without a stacking context", (width) => {
    const spy = client("spy");
    spy.element("details").clientWidth = width;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tour, phase: "extras", step: "spyProperties", spyTarget: "properties-pane" } });
    expect(spy.element("details").classList.contains("inspector-narrow")).toBe(width <= 560);
  });

  it("moves the feature spotlight and keeps tutorial navigation working", () => {
    const spy = client("spy");
    const tutorial = { ...tour, phase: "extras", step: "spyPick", spyTarget: "pick", buttons: [{ id: "next", label: "Next" }] };
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    expect(spy.element("pick").classList.contains("tutorial-spotlight")).toBe(true);
    spy.element("extra-tutorial-body").scrollTop = 35;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    expect(spy.element("extra-tutorial-body").scrollTop).toBe(35);
    const actions = spy.element("extra-tutorial-body").querySelector(".tutorial-actions")!;
    actions.children[0].listeners.click();
    expect(spy.posts.at(-1)).toEqual({ type: "tour", action: "back" });
    actions.children[1].listeners.click();
    expect(spy.posts.at(-1)).toEqual({ type: "tour", action: "next" });
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tutorial, step: "spyBrowse", spyTarget: "tree-pane" } });
    expect(spy.element("extra-tutorial-body").scrollTop).toBe(0);
    expect(spy.element("pick").classList.contains("tutorial-spotlight")).toBe(false);
    expect(spy.element("tree-pane").classList.contains("tutorial-spotlight")).toBe(true);
    spy.element("locator-panel").hidden = true;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tutorial, step: "spyLocators", spyTarget: "locator-panel" } });
    expect(spy.element("tree-pane").classList.contains("tutorial-spotlight")).toBe(false);
    expect(spy.element("details").classList.contains("tutorial-spotlight")).toBe(true);
    spy.send({ type: "tour", dim: false, spyLit: false });
    expect(spy.element("details").classList.contains("tutorial-spotlight")).toBe(false);
  });

  it("shows and clears definitions and the separate property section together", () => {
    const spy = client("spy");
    expect(spy.element("property-groups").hidden).toBe(true);
    expect(spy.element("definitions-group").hidden).toBe(true);
    expect(spy.element("properties-empty").hidden).toBe(false);
    spy.send({ type: "selected", nodeId: "pane", properties: { info: { name: "VS Code", controlType: "Pane" }, properties: {} } });
    expect(spy.element("property-groups").hidden).toBe(false);
    expect(spy.element("definitions-group").hidden).toBe(false);
    expect(spy.element("properties-empty").hidden).toBe(true);
    expect(spy.element("properties").children.length).toBeGreaterThan(0);
    spy.send({ type: "roots", nodes: [] });
    expect(spy.element("property-groups").hidden).toBe(true);
    expect(spy.element("definitions-group").hidden).toBe(true);
    expect(spy.element("properties-empty").hidden).toBe(false);
  });

  describe("Spy tutorial card", () => {
    const tutorial = { ...tour, phase: "extras", buttons: [{ id: "next", label: "Next" }] };
    function open(step: string, spyTarget?: string) {
      const spy = client("spy", { width: 900 });
      const guide = spy.element("extra-tutorial");
      guide.offsetWidth = 320;
      guide.offsetHeight = 150;
      spy.element("pick").rect = { top: 8, bottom: 36, left: 10, right: 120 };
      spy.element("tree-pane").rect = { top: 50, bottom: 320, left: 10, right: 400 };
      spy.element("details").rect = { top: 50, bottom: 320, left: 480, right: 890 };
      spy.element("properties-pane").rect = { top: 50, bottom: 320, left: 480, right: 890 };
      spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tutorial, step, spyTarget } });
      return { spy, guide };
    }
    const at = (guide: Node) => [guide.dataset.side, guide.style.left, guide.style.top];
    it("sits below a control at the top and points at it", () => {
      const { spy, guide } = open("spyPick", "pick");
      expect(at(guide)).toEqual(["bottom", "8px", "48px"]);
      expect(guide.style.values.get("--arrow-x")).toBe("57px");
      expect(spy.element("tutorial-scrim").hidden).toBe(false);
    });
    it("moves beside a part too tall to sit below, on the side with room", () => {
      const tree = open("spyBrowse", "tree-pane");
      expect(at(tree.guide)).toEqual(["right", "412px", "110px"]);
      expect(tree.guide.style.values.get("--arrow-y")).toBe("75px");
      const details = open("spyProperties", "properties-pane");
      expect(at(details.guide)).toEqual(["left", "148px", "110px"]);
      expect(details.spy.element("properties-pane").classList.contains("tutorial-spotlight")).toBe(true);
    });
    it("blurs the background of the centered introduction without a spotlight", () => {
      const { spy, guide } = open("spy");
      expect(at(guide)).toEqual([undefined, "290px", "85px"]);
      expect(spy.element("tutorial-scrim").hidden).toBe(false);
      expect(readFileSync("media/spy/spy.css", "utf8")).toContain("backdrop-filter: blur(3px)");
    });
    it.each(["spy", "spyPick", "spyBrowse", "spySelection", "spyDefinitions", "spyLocators", "spyProperties", "test"])("omits skip and cancel controls from %s", (step) => {
      const { spy } = open(step);
      const body = spy.element("extra-tutorial-body");
      expect(body.querySelector(".tutorial-foot")).toBeUndefined();
      expect(body.querySelector(".tutorial-skip")).toBeUndefined();
      expect(body.querySelector(".tutorial-cancel")).toBeUndefined();
      expect(body.querySelector(".tutorial-actions")).toBeDefined();
    });
    it("takes the dulling away with the card", () => {
      const { spy } = open("spyBrowse", "tree-pane");
      spy.send({ type: "tour", dim: false, spyLit: false });
      expect(spy.element("tutorial-scrim").hidden).toBe(true);
      expect(spy.element("tree-pane").classList.contains("tutorial-spotlight")).toBe(false);
    });
  });

  it.each(["complete", "spy", "test"])("labels the %s card as the optional extra feature tutorial", (step) => {
    const page = client("setup");
    page.send({ type: "model", model: { ...model, tour: {
      ...tour, step, phase: step === "complete" ? "setup" : "extras",
      progress: step === "complete" ? undefined : { index: 1, total: 2 },
    } } });
    expect(page.element("setup-guide").querySelector(".callout-step")?.textContent)
      .toBe("Optional Extra Feature Tutorial");
  });

  it("retains numbered progress for the required setup steps", () => {
    const page = client("setup");
    page.send({ type: "model", model: { ...model, tour: {
      ...tour, step: "project", phase: "setup", progress: { index: 4, total: 7 },
    } } });
    expect(page.element("setup-guide").querySelector(".callout-step")?.textContent).toBe("Step 4 of 7");
  });

  it("shows application controls only after project creation, without unrelated package extras", () => {
    const page = client("setup");
    const input = {
      trusted: true,
      interpreter: {
        name: "Python", version: "3.14.7", path: "C:/python.exe",
        strip: {
          state: "ok" as const, text: "wintestkit 0.1.1",
          source: { value: "local" as const, wheel: "C:/build/wintestkit.whl" },
          action: { id: "installPackage" as const, label: "Install selected wheel" },
        },
      },
      tour: {
        step: "project" as const, phase: "setup" as const, kind: "todo" as const,
        title: "Create the test project", text: "Click Initialize project.", lit: ["project" as const],
        panel: false, buttons: [], canBack: true, canNext: false,
      },
    };
    const showProject = () => page.send({ type: "model", model: buildTestAppModel(input) });
    showProject();
    const card = page.element("card");
    expect(card.querySelectorAll("[data-area]").map((node) => node.dataset.area))
      .toEqual(["interpreter", "package", "initProject"]);
    expect(card.querySelector(".tile-title")?.textContent).toBe("Python");
    expect(card.querySelector(".tile-subtitle")?.textContent).toBe("Python 3.14.7");
    expect(card.querySelector(".strip-text")?.textContent).toBe("wintestkit 0.1.1");
    expect(card.querySelector(".package-source")).toBeUndefined();
    expect(card.querySelector(".strip-action")).toBeUndefined();
    expect(page.element("pages").hidden).toBe(false);
    page.send({ type: "model", model: buildTestAppModel({
      ...input, tour: { ...input.tour, step: "package", lit: ["package"] },
    }) });
    expect(card.querySelector(".package-source-select")?.value).toBe("local");
    expect(card.querySelector(".package-source-path")?.textContent).toBe("C:/build/wintestkit.whl");
    expect(card.querySelector(".strip-action")?.textContent).toBe("Install selected wheel");
    showProject();
    expect(card.querySelector(".package-source")).toBeUndefined();
    expect(card.querySelector(".strip-action")).toBeUndefined();
    expect(card.querySelectorAll("[data-area]").map((node) => node.dataset.area))
      .toEqual(["interpreter", "package", "initProject"]);
    page.send({ type: "model", model: buildTestAppModel({
      ...input, project: { name: "demo" },
      tour: { ...input.tour, step: "app", lit: ["app"] },
    }) });
    expect(card.querySelectorAll("[data-area]").map((node) => node.dataset.area))
      .toEqual(["interpreter", "package", "app", "mode", "launch"]);
    expect(card.querySelector(".package-source")).toBeUndefined();
    expect(card.querySelector(".strip-action")).toBeUndefined();
  });
  it("immediately spins and prevents repeated project initialization clicks", () => {
    const page = client("setup");
    const projectTour = { ...tour, step: "project", lit: ["project"] };
    const tiles = [{ id: "initProject", title: "Initialize project", codicon: "new-folder" }];
    page.send({ type: "model", model: { ...model, tiles, tour: projectTour } });
    expect(page.element("setup-guide").querySelector(".callout-actions")).toBeUndefined();
    const button = page.element("card").querySelector(".tile")!;
    button.listeners.click();
    expect(button.querySelector(".tile-title")?.textContent).toBe("Initializing project…");
    expect(button).toMatchObject({ disabled: true });
    expect(button.querySelector(".codicon-loading")?.classList.contains("codicon-modifier-spin")).toBe(true);
    button.listeners.click();
    expect(page.posts).toEqual([{ type: "ready" }, { type: "tile", id: "initProject" }]);
    page.send({ type: "model", model: { ...model, tiles: [{ ...tiles[0], codicon: "loading", disabled: true, busy: true }], tour: projectTour } });
    expect(page.element("card").querySelector(".codicon-loading")?.classList.contains("codicon-modifier-spin")).toBe(true);
    page.send({ type: "model", model: { ...model, tiles, tour: projectTour } });
    expect(page.element("card").querySelector(".tile")).toMatchObject({ disabled: false });
  });
  it("shows the source dropdown only when the host supplies development controls", () => {
    const page = client("setup");
    const strip = { state: "missing", text: "not installed" };
    page.send({ type: "model", model: { ...model, tiles: [{ ...model.tiles[0], strip }] } });
    expect(page.element("card").querySelector(".package-source-select")).toBeUndefined();
    page.send({ type: "model", model: { ...model, tiles: [{ ...model.tiles[0], strip: { ...strip, source: { value: "remote" } } }] } });
    const select = page.element("card").querySelector(".package-source-select")!;
    expect(select.children.map((option) => option.textContent)).toEqual(["Remote (PyPI)", "Local wheel"]);
    select.value = "local";
    select.listeners.change();
    expect(page.posts.at(-1)).toEqual({ type: "packageSource", source: "local" });
  });
  it("keeps only the package strip interactive and installs through its button", () => {
    const page = client("setup");
    page.send({
      type: "model",
      model: {
        ...model,
        tiles: [{
          ...model.tiles[0],
          strip: { state: "missing", text: "wintestkit not installed", action: { id: "installPackage", label: "Install" } },
        }],
        tour: { ...tour, lit: ["package"] },
      },
    });
    const card = page.element("card");
    const areas = card.querySelectorAll("[data-area]");
    expect(areas.map((node) => [node.dataset.area, node.inert, node.classList.contains("lit")]))
      .toEqual([["interpreter", true, false], ["package", false, true]]);
    expect(card.querySelector(".callout-actions")).toBeUndefined();
    const install = card.querySelector(".strip-action");
    expect(install?.textContent).toBe("Install");
    install?.listeners.click();
    expect(page.posts.at(-1)).toEqual({ type: "tile", id: "installPackage" });
  });
  it("labels setup cancellation and reuses the Python SVG for the interpreter path", () => {
    const page = client("setup");
    const icon = "data:image/svg+xml;base64,PHN2Zy8+";
    page.send({
      type: "model",
      model: {
        ...model,
        tiles: [{ ...model.tiles[0], icon }],
        tour: { ...tour, step: "interpreter", detail: "C:/Python/python.exe" },
      },
    });
    const guide = page.element("setup-guide");
    expect(guide.querySelector(".callout-foot")?.querySelector(".secondary")?.textContent).toBe("Cancel WinTestKit Setup");
    expect(guide.querySelector(".danger")).toBeUndefined();
    guide.querySelector(".callout-foot")?.querySelector(".secondary")?.listeners.click();
    expect(page.posts.at(-1)).toEqual({ type: "tour", action: "disable" });
    const skip = guide.querySelector(".callout-foot")?.children[1];
    expect(skip?.textContent).toBe("Skip tutorial");
    skip?.listeners.click();
    expect(page.posts.at(-1)).toEqual({ type: "tour", action: "skip" });
    expect(guide.querySelector(".callout-detail-icon")?.src).toBe(icon);
    expect(guide.querySelector(".callout-detail-icon")?.alt).toBe("");
    expect(guide.querySelector(".callout-detail")?.children[1].textContent).toBe("C:/Python/python.exe");
    page.send({
      type: "model",
      model: { ...model, tour: { ...tour, step: "machine", detail: "Check failed" } },
    });
    expect(guide.querySelector(".callout-detail-icon")).toBeUndefined();
    expect(guide.querySelector(".callout-detail")?.children[0].classList.contains("codicon-device-desktop")).toBe(true);
  });
  it.each([
    ["interpreter", "terminal"],
    ["package", "package"],
    ["machine", "device-desktop"],
    ["project", "folder-library"],
    ["app", "window"],
    ["mode", "settings-gear"],
    ["launch", "play"],
    ["spy", "inspect"],
    ["test", "beaker"],
    ["complete", "check"],
  ])("uses a meaningful detail icon for the %s guide step", (step, icon) => {
    const page = client("setup");
    page.send({ type: "model", model: { ...model, tour: { ...tour, step, detail: "Step details" } } });
    const detail = page.element("setup-guide").querySelector(".callout-detail");
    expect(detail?.children[0].classList.contains("codicon-" + icon)).toBe(true);
    expect(detail?.children[1].textContent).toBe("Step details");
    expect(page.element("setup-guide").querySelector(".codicon-debug-breakpoint-log-unverified")).toBeUndefined();
  });
  it("omits the detail icon for an unknown guide step instead of showing a diamond", () => {
    const page = client("setup");
    page.send({ type: "model", model: { ...model, tour: { ...tour, step: "unknown", detail: "Step details" } } });
    const detail = page.element("setup-guide").querySelector(".callout-detail");
    expect(detail?.children).toHaveLength(1);
    expect(detail?.children[0].textContent).toBe("Step details");
  });
  it("marks installation failures red and puts a warning triangle beside the error", () => {
    const page = client("setup");
    page.send({
      type: "model",
      model: { ...model, tour: { ...tour, kind: "attention", detail: "ERROR: No matching distribution found for wintestkit" } },
    });
    const guide = page.element("setup-guide");
    expect(guide.querySelector(".callout")?.dataset.kind).toBe("attention");
    const detail = guide.querySelector(".callout-error");
    expect(detail?.children[0].classList.contains("codicon-warning")).toBe(true);
    expect(detail?.children[1].textContent).toBe("ERROR: No matching distribution found for wintestkit");
    expect(detail?.children[0].classList.contains("codicon-debug-breakpoint-log-unverified")).toBe(false);
  });
  it("keeps the guide below the controls and preserves Test Target scrolling on refresh", () => {
    const page = client("setup");
    const card = page.element("card");
    const target = page.element("test-target");
    const guide = page.element("setup-guide");
    page.send({ type: "model", model });
    expect(card.querySelector(".callout")).toBeUndefined();
    expect(guide.querySelector(".callout")).toBeDefined();
    expect(guide.style.values.has("--guide-top")).toBe(false);
    target.scrollTop = 45;
    guide.querySelector(".callout")!.scrollTop = 30;
    page.send({ type: "model", model });
    expect(target.scrollTop).toBe(45);
    expect(guide.querySelector(".callout")?.scrollTop).toBe(30);
    page.send({ type: "model", model: { ...model, tour: { ...tour, step: "app" } } });
    expect(guide.querySelector(".callout")?.scrollTop).toBe(0);
    page.send({ type: "model", model: { ...model, tour: undefined } });
    expect(guide.querySelector(".callout")).toBeUndefined();
    expect(target.scrollTop).toBe(45);
  });

  it("makes dimmed tiles inert and restores them when the guide closes", () => {
    const page = client("setup");
    page.send({ type: "model", model });
    expect(
      page
        .element("card")
        .querySelectorAll("[data-area]")
        .map((node) => node.inert),
    ).toEqual([false, true]);
    page.send({ type: "model", model: { ...model, tour: undefined } });
    expect(
      page
        .element("card")
        .querySelectorAll("[data-area]")
        .every((node) => !node.inert),
    ).toBe(true);
  });

  it("never repositions the instructions around the highlighted button during the first seven steps", () => {
    const page = client("setup");
    const target = page.element("test-target");
    target.scrollTop = 24;
    for (const step of ["interpreter", "package", "machine", "project", "app", "mode", "launch"]) {
      page.send({ type: "model", model: { ...model, tour: { ...tour, step, lit: [step] } } });
      expect(page.element("setup-guide").querySelector(".callout")).toBeDefined();
      expect(page.element("setup-guide").style.values.has("--guide-top")).toBe(false);
      expect(target.scrollTop).toBe(24);
    }
  });

  it("shows the guide when no tiles exist", () => {
    const page = client("setup");
    page.send({ type: "model", model: { ...model, tiles: [] } });
    expect(
      page
        .element("setup-guide")
        .querySelector(".callout")
    ).toBeDefined();
  });

  it("renders bounded expandable inspection data as text while retaining flat property tables", () => {
    const page = client("spy");
    const scalar = { name: "<script>unsafe</script>", typeName: "String", kind: "scalar", value: "<img src=x onerror=unsafe>" };
    page.send({ type: "selected", nodeId: "control", properties: {
      info: { name: "Control", controlType: "Button" }, properties: { Legacy: "flat" },
      inspection: [{ name: "Model", typeName: "UIA", kind: "object", children: [scalar,
        { name: "Unavailable", typeName: "UIA", kind: "unavailable", status: "Not supported" }] }],
    } });
    expect(page.element("inspection-section").hidden).toBe(false);
    const branch = page.element("inspection-tree").children[0];
    expect(branch.children[0].textContent).toBe("Model (UIA)");
    expect(branch.children[1].textContent).toContain("<img src=x onerror=unsafe>");
    expect(branch.children[2].textContent).toContain("Not supported");
    expect(page.element("all-properties").children).toHaveLength(1);
    page.send({ type: "allProperties", nodeId: "control", properties: {
      info: {}, properties: {}, inspection: Array.from({ length: 1000 }, () => scalar),
    } });
    expect(page.element("inspection-tree").children).toHaveLength(501);
    expect(page.element("inspection-tree").children.at(-1)?.textContent).toContain("limit reached");
  });

  describe("suggested locator", () => {
    const select = (page: ReturnType<typeof client>, nodeId = "control") =>
      page.send({ type: "selected", nodeId, properties: { info: { name: nodeId, controlType: "Button" }, properties: {} } });
    const generate = (page: ReturnType<typeof client>) => page.element("generate").listeners.click();
    const requests = (page: ReturnType<typeof client>) =>
      page.posts.filter((post) => (post as { type?: string }).type === "generateLocator");
    it("offers only the button, without the actions, instead of generating by itself", () => {
      const page = client("spy");
      select(page);
      expect(page.element("locator-slot").hidden).toBe(false);
      expect(page.element("generate").hidden).toBe(false);
      expect(page.element("generate").disabled).toBe(false);
      expect(page.element("locator-busy").hidden).toBe(true);
      expect(page.element("locator-result").hidden).toBe(true);
      expect(page.element("locator-actions").hidden).toBe(true);
      expect(requests(page)).toHaveLength(0);
    });

    it("shows a spinner while generating and the locator when it arrives", () => {
      const page = client("spy");
      select(page);
      generate(page);
      expect(requests(page)).toEqual([{ type: "generateLocator", nodeId: "control" }]);
      expect(page.element("locator-busy").hidden).toBe(false);
      expect(page.element("locator-slot").hidden).toBe(false);
      expect(page.element("generate").hidden).toBe(true);
      expect(page.element("locator-result").hidden).toBe(true);
      expect(page.element("locator-actions").hidden).toBe(true);
      page.send({ type: "suggestion", nodeId: "control", suggestion: {
        helpers: [], code: 'Button(name="Save")', attributeName: "save", unique: true, matchCount: 1, strategy: "name",
      } });
      expect(page.element("locator-busy").hidden).toBe(true);
      expect(page.element("generate").hidden).toBe(true);
      expect(page.element("locator-slot").hidden).toBe(true); // no empty row between the title and the code
      expect(page.element("locator-result").hidden).toBe(false);
      expect(page.element("locator-actions").hidden).toBe(false);
      expect(page.element("code").textContent).toBe('save = Button(name="Save")');
      expect(page.element("badge").hidden).toBe(false);
      expect(page.element("copy").disabled).toBe(false);
      expect(page.element("add").disabled).toBe(false);
    });

    it("keeps the spinner when the details arrive after the button was pressed", () => {
      const page = client("spy");
      select(page);
      generate(page);
      select(page);
      expect(page.element("locator-busy").hidden).toBe(false);
    });

    it("explains a failure and lets the user try again", () => {
      const page = client("spy");
      select(page);
      generate(page);
      page.send({ type: "suggestionUnavailable", nodeId: "control", reason: "pipe closed" });
      expect(page.element("locator-busy").hidden).toBe(true);
      expect(page.element("locator-result").hidden).toBe(false);
      expect(page.element("code").textContent).toBe("pipe closed");
      expect(page.element("locator-slot").hidden).toBe(false);
      expect(page.element("generate").hidden).toBe(false);
      expect(page.element("generate").disabled).toBe(false);
      expect(page.element("generate-label").textContent).toBe("Try again");
      expect(page.element("locator-actions").hidden).toBe(true);
      generate(page);
      expect(requests(page)).toHaveLength(2);
      expect(page.element("locator-busy").hidden).toBe(false);
    });

    it("ignores a locator for an object that is no longer selected", () => {
      const page = client("spy");
      select(page, "next");
      generate(page);
      page.send({ type: "suggestion", nodeId: "control", suggestion: {
        helpers: [], code: "Button()", attributeName: "old", unique: true, matchCount: 1, strategy: "name",
      } });
      expect(page.element("locator-busy").hidden).toBe(false);
      expect(page.element("code").textContent).toBe("");
    });

    it("does nothing when there is no selection", () => {
      const page = client("spy");
      generate(page);
      expect(requests(page)).toHaveLength(0);
    });
  });

  describe("object preview", () => {
    const element = "data:image/webp;base64,ZWxlbWVudA==";
    const context = "data:image/webp;base64,d2luZG93";
    const select = (page: ReturnType<typeof client>, nodeId = "control") =>
      page.send({ type: "selected", nodeId, properties: { info: { name: nodeId, controlType: "Button" }, properties: {} } });
    const click = (page: ReturnType<typeof client>, id: string) => page.element(id).listeners.click();

    it("shows the element by default and switches to the outlined window and back", () => {
      const page = client("spy");
      select(page);
      expect(page.element("object-preview").hidden).toBe(false);
      expect(page.element("object-preview-image").hidden).toBe(true);
      expect(page.element("object-preview-status").textContent).toContain("Capturing");
      page.send({ type: "objectPreview", nodeId: "control", preview: { elementDataUrl: element, windowDataUrl: context } });
      expect(page.element("object-preview-image").src).toBe(element);
      expect(page.element("object-preview-image").hidden).toBe(false);
      expect(page.element("object-preview-status").textContent).toContain("Live capture");
      click(page, "preview-context");
      expect(page.element("object-preview-image").src).toBe(context);
      expect(page.element("object-preview-status").textContent).toContain("outlined in red");
      click(page, "preview-element");
      expect(page.element("object-preview-image").src).toBe(element);
    });

    it("keeps the chosen view when another object is selected", () => {
      const page = client("spy");
      select(page);
      page.send({ type: "objectPreview", nodeId: "control", preview: { elementDataUrl: element, windowDataUrl: context } });
      click(page, "preview-context");
      select(page, "next");
      page.send({ type: "objectPreview", nodeId: "next", preview: { elementDataUrl: element, windowDataUrl: context } });
      expect(page.element("object-preview-image").src).toBe(context);
    });

    it("opens whichever view is showing in the image viewer, and only once there is an image", () => {
      const page = client("spy");
      select(page);
      expect(page.element("preview-open").disabled).toBe(true);
      click(page, "preview-open");
      expect(page.posts.some((post) => (post as { type?: string }).type === "openPreview")).toBe(false);
      page.send({ type: "objectPreview", nodeId: "control", preview: { elementDataUrl: element, windowDataUrl: context } });
      expect(page.element("preview-open").disabled).toBe(false);
      click(page, "preview-open");
      expect(page.posts.at(-1)).toEqual({ type: "openPreview", view: "element", dataUrl: element });
      click(page, "preview-context");
      page.element("object-preview-image").listeners.click();
      expect(page.posts.at(-1)).toEqual({ type: "openPreview", view: "window", dataUrl: context });
    });

    it("ignores a preview for an object that is no longer selected", () => {
      const page = client("spy");
      select(page, "next");
      page.send({ type: "objectPreview", nodeId: "control", preview: { elementDataUrl: element, windowDataUrl: context } });
      expect(page.element("object-preview-image").hidden).toBe(true);
    });

    it("explains why there is no image and rejects anything that is not a WebP data URL", () => {
      const page = client("spy");
      select(page);
      page.send({ type: "objectPreview", nodeId: "control", reason: "The window cannot be captured." });
      expect(page.element("object-preview-image").hidden).toBe(true);
      expect(page.element("object-preview-status").textContent).toBe("The window cannot be captured.");
      page.send({ type: "objectPreview", nodeId: "control", preview: {
        elementDataUrl: "https://example.test/a.png", windowDataUrl: context,
      }, reason: "Unsafe image." });
      expect(page.element("object-preview-image").hidden).toBe(true);
      expect(page.element("object-preview-status").textContent).toBe("Unsafe image.");
    });
  });

  it("shows the saved last-test images in explicit offline mode and ignores stale live details", () => {
    const page = client("spy");
    page.send({ type: "savedDefinition", id: "pages/Page.py::Page.button", qualname: "Page.button", preview: {
      capturedAt: "2026-10-20T12:34:56.000Z", elementDataUrl: "data:image/webp;base64,YWJj",
      windowDataUrl: "data:image/webp;base64,dW51c2Vk",
    } });
    expect(page.element("selection-name").textContent).toBe("Page.button");
    expect(page.element("object-preview-image").src).toBe("data:image/webp;base64,YWJj");
    expect(page.element("object-preview-status").textContent).toContain("2026-10-20T12:34:56.000Z");
    expect(page.element("object-preview-status").textContent).toContain("Not a live capture");
    expect(page.element("highlight").disabled).toBe(true);
    expect(page.element("load-properties").disabled).toBe(true);
    page.send({ type: "selected", nodeId: "old", properties: { info: { name: "stale" }, properties: {} } });
    expect(page.element("selection-name").textContent).toBe("Page.button");
    const before = page.posts.length;
    page.dispatch("click", "highlight");
    page.dispatch("click", "load-properties");
    expect(page.posts).toHaveLength(before);
  });

  it("keeps partial enumeration warnings visible alongside retained nodes", () => {
    const page = client("spy");
    page.send({ type: "enumerationIncomplete", message: "Incomplete object enumeration. Window closed" });
    page.send({ type: "roots", nodes: [] });
    expect(page.element("enumeration-status").hidden).toBe(false);
    expect(page.element("enumeration-status").textContent).toContain("Window closed");
  });

  it("fails open without a local actionable callout and preserves Spy tutorial hover", () => {
    const page = client("spy");
    page.send({ type: "tour", dim: true, spyLit: false });
    expect(page.body.inert).toBe(false);
    expect(page.body.classList.contains("tour-dim")).toBe(false);
    page.send({ type: "tour", dim: true, spyLit: true });
    expect(page.body.inert).toBe(false);
    expect(page.body.classList.contains("tour-dim")).toBe(false);
    expect(page.element("pick").classList.contains("tour-lit")).toBe(true);
    page.send({ type: "tour", dim: false, spyLit: false });
    expect(page.body.inert).toBe(false);
    expect(page.element("pick").classList.contains("tour-lit")).toBe(false);
  });
});
