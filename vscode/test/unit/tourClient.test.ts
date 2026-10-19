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
  style = {
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
    return {
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

function client(file: "setup" | "spy") {
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
  const api = { postMessage(message: unknown) { posts.push(message); } };
  vm.runInNewContext(
    readFileSync("media/" + file + "/" + file + ".js", "utf8"),
    {
      document: {
        body,
        getElementById: element,
        createElement: () => new Node(),
      },
      window: {
        innerHeight: 320,
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
  return { body, element, posts, send: (data: unknown) => receive({ data }) };
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
    expect(spy.element("extra-tutorial").querySelector(".tutorial-title")?.textContent).toBe("Meet Spy");
    expect(spy.element("extra-tutorial").querySelector(".tutorial-arrival")?.textContent).toBe("↘");
    spy.element("extra-tutorial").querySelector(".tutorial-cancel")?.listeners.click();
    expect(spy.posts.at(-1)).toEqual({ type: "tour", action: "disable" });
    spy.element("extra-tutorial").querySelector(".tutorial-skip")?.listeners.click();
    expect(spy.posts.at(-1)).toEqual({ type: "tour", action: "skip" });
    spy.send({ type: "tour", dim: false, spyLit: false });
    expect(spy.element("extra-tutorial").hidden).toBe(true);
  });

  it("moves the feature spotlight and keeps tutorial navigation working", () => {
    const spy = client("spy");
    const tutorial = { ...tour, phase: "extras", step: "spyPick", spyTarget: "pick", buttons: [{ id: "next", label: "Next" }] };
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    expect(spy.element("pick").classList.contains("tutorial-spotlight")).toBe(true);
    spy.element("extra-tutorial").scrollTop = 35;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial });
    expect(spy.element("extra-tutorial").scrollTop).toBe(35);
    const actions = spy.element("extra-tutorial").querySelector(".tutorial-actions")!;
    actions.children[0].listeners.click();
    expect(spy.posts.at(-1)).toEqual({ type: "tour", action: "back" });
    actions.children[1].listeners.click();
    expect(spy.posts.at(-1)).toEqual({ type: "tour", action: "next" });
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tutorial, step: "spyBrowse", spyTarget: "tree-pane" } });
    expect(spy.element("extra-tutorial").scrollTop).toBe(0);
    expect(spy.element("pick").classList.contains("tutorial-spotlight")).toBe(false);
    expect(spy.element("tree-pane").classList.contains("tutorial-spotlight")).toBe(true);
    spy.element("locator-panel").hidden = true;
    spy.send({ type: "tour", dim: false, spyLit: true, tutorial: { ...tutorial, step: "spyLocators", spyTarget: "locator-panel" } });
    expect(spy.element("tree-pane").classList.contains("tutorial-spotlight")).toBe(false);
    expect(spy.element("details").classList.contains("tutorial-spotlight")).toBe(true);
    spy.send({ type: "tour", dim: false, spyLit: false });
    expect(spy.element("details").classList.contains("tutorial-spotlight")).toBe(false);
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

  it("unlocks the whole Spy panel during its extra, not only Pick element", () => {
    const page = client("spy");
    page.send({ type: "tour", dim: true, spyLit: false });
    expect(page.body.inert).toBe(true);
    expect(page.body.classList.contains("tour-dim")).toBe(true);
    page.send({ type: "tour", dim: true, spyLit: true });
    expect(page.body.inert).toBe(false);
    expect(page.body.classList.contains("tour-dim")).toBe(false);
    expect(page.element("pick").classList.contains("tour-lit")).toBe(true);
    page.send({ type: "tour", dim: false, spyLit: false });
    expect(page.body.inert).toBe(false);
    expect(page.element("pick").classList.contains("tour-lit")).toBe(false);
  });
});
