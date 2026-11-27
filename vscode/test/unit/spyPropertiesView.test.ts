import { readFileSync } from "node:fs";
import { JSDOM, VirtualConsole } from "jsdom";
import { describe, expect, it } from "vitest";
import { DEFAULT_BASIC_PROPERTIES } from "../../src/spy/basicProperties";

/**
 * Headless acceptance tests for the Properties sidebar and the Spy panel. Both are the same page
 * (spy.html + spy.css + spy.js) told apart by the body class the host sets. jsdom has no layout, so
 * visibility is decided the way a browser decides display: the `hidden` attribute and the real
 * stylesheet, on the element and every ancestor.
 */
type Surface = "properties-view" | "spy-view";
type Message = Record<string, unknown>;

const html = readFileSync("media/spy/spy.html", "utf8");
const css = readFileSync("media/spy/spy.css", "utf8");
const labels = readFileSync("media/spy/treeLabels.js", "utf8");
const script = readFileSync("media/spy/spy.js", "utf8");

function open(surface: Surface, state: Record<string, unknown> = {}, options: { narrow?: boolean } = {}) {
  const errors: string[] = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(`jsdomError: ${error.message}`));
  virtualConsole.on("error", (...args) => errors.push(`console.error: ${args.join(" ")}`));
  const page = html
    .replaceAll("{{viewClass}}", surface)
    .replace(/<link rel="stylesheet"[^>]*>/g, "")
    .replace("</head>", () => `<style>${css}</style></head>`);
  const dom = new JSDOM(page, { runScripts: "outside-only", virtualConsole });
  const posts: Message[] = [];
  let saved: Record<string, unknown> | undefined = state;
  Object.assign(dom.window, {
    acquireVsCodeApi: () => ({
      postMessage: (message: Message) => posts.push(message),
      getState: () => saved,
      setState: (next: Record<string, unknown>) => { saved = next; },
    }),
    matchMedia: () => ({ matches: !!options.narrow, addEventListener() {} }),
    requestAnimationFrame: (fn: () => void) => fn(),
  });
  dom.window.addEventListener("error", (event) => errors.push(`error event: ${event.message}`));
  dom.window.eval(`${labels}\n${script}`);
  const doc = dom.window.document;
  const send = (...messages: Message[]) => {
    for (const data of messages) dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  };
  /** Why an element cannot be seen (itself or any ancestor), or undefined when it can. */
  const hiddenReason = (selector: string | Element): string | undefined => {
    let node: Element | null = typeof selector === "string" ? doc.querySelector(selector) : selector;
    if (!node) return `${selector} is missing`;
    for (; node; node = node.parentElement) {
      const id = `${node.tagName.toLowerCase()}${node.id ? "#" + node.id : ""}`;
      if ((node as HTMLElement).hidden) return `${id} has the hidden attribute`;
      if (dom.window.getComputedStyle(node).display === "none") return `${id} has display:none`;
    }
    return undefined;
  };
  const visible = (selector: string) => hiddenReason(selector) === undefined;
  const text = (selector: string) => doc.querySelector(selector)?.textContent ?? "";
  const names = () => [...doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr[data-name]")].map((row) => row.dataset.name);
  const headings = () => [...doc.querySelectorAll("#sidebar-rows tr.sidebar-group")].map((row) => row.textContent);
  const value = (name: string) => doc.querySelector(`#sidebar-rows [data-name="${name}"] td`)?.textContent;
  const visibleButtons = (label: string) => [...doc.querySelectorAll<HTMLButtonElement>("button")].filter((button) => button.textContent?.trim() === label && hiddenReason(button) === undefined);
  const type = (input: HTMLInputElement, next: string) => { input.value = next; input.dispatchEvent(new dom.window.Event("input")); };
  return { dom, doc, posts, send, errors, hiddenReason, visible, text, names, headings, value, visibleButtons, type, state: () => saved };
}

const windowNode = { nodeId: "win", source: "wpf", hasChildren: true, info: { controlType: "Window", name: "Fixture", className: "FixtureWindow", processId: 42, processName: "Fixture.exe" } };
const borderNode = { nodeId: "border", source: "wpf", hasChildren: true, info: { controlType: "Pane", name: "", className: "Border" }, identity: { type: "System.Windows.Controls.Border" }, wpfText: "", wpfOrdinal: 1 };
const presenterNode = {
  nodeId: "presenter", source: "wpf", hasChildren: false,
  info: { controlType: "Pane", name: "", className: "ContentPresenter", isEnabled: true, isOffscreen: false, rect: { left: 10, top: 20, width: 30, height: 40 } },
  identity: { type: "System.Windows.Controls.ContentPresenter", xName: "contentSite" },
};
const presenterProperties = {
  source: "wpf",
  info: presenterNode.info,
  ancestors: [windowNode, borderNode],
  uiaMapped: true,
  properties: {
    ClrFullClassName: "System.Windows.Controls.ContentPresenter", "x:Name": "contentSite", AutomationId: "", Name: "", ControlType: "Pane",
    Bounds: "{left:10}", Visible: "True", IsEnabled: "True", HasKeyboardFocus: "False", ProcessId: "42", WindowHandle: "7",
  },
  uia: { properties: { ClassName: "ContentPresenter", FrameworkId: "WPF" }, inspection: [] },
};
const member = (name: string, extra: Record<string, unknown> = {}) => ({
  memberKey: `clr:${name}`, name, category: "clrProperty", visibility: "public", readable: true,
  pathSegment: { kind: "property", name }, declaringType: "System.Windows.Controls.ContentPresenter", declaredType: "System.Object", ...extra,
});
const managed = (extra: Record<string, unknown> = {}): Message => ({
  type: "managedPanel", sequence: 1, visible: true, state: "ready",
  object: { objectId: "o", type: { fullName: "System.Windows.Controls.ContentPresenter", assemblyName: "PresentationFramework", baseTypes: [] } },
  rows: [
    { member: member("Content"), value: { status: "ok", kind: "string", scalar: "Hello", runtimeType: "System.String" } },
    { member: member("ContentTemplate"), value: { status: "ok", kind: "null", runtimeType: "" } },
    { member: member("Name"), value: { status: "ok", kind: "string", scalar: "contentSite", runtimeType: "System.String" } },
    { member: member("IsEnabled"), value: { status: "ok", kind: "bool", scalar: true, runtimeType: "System.Boolean" } },
    { member: member("Margin"), value: { status: "ok", kind: "string", scalar: "0,0,0,0", runtimeType: "System.Windows.Thickness" } },
    { member: member("Parent", { declaredType: "System.Windows.DependencyObject" }), value: { status: "ok", kind: "object", runtimeType: "System.Windows.Controls.Border" } },
    { member: { ...member("_count", { category: "clrField", visibility: "private", readable: false, reason: "nonPublic" }), pathSegment: { kind: "field", name: "_count", memberKey: "clrField|_count", declaringType: "System.Windows.Controls.ContentPresenter" } }, value: { status: "ok", kind: "int", scalar: 7, runtimeType: "System.Int32" } },
  ],
  ...extra,
});
// What the host's state message carries for the Basic view: the stored rows and the list Reset restores.
const basicState: Message = { type: "state", basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES] };
// The tooltip on a row's name cell: the description other rows have, as native title text.
const tooltip = (view: { doc: Document }, name: string) => view.doc.querySelector<HTMLElement>(`#sidebar-rows [data-name="${name}"] th`)?.title ?? "";
// The messages the host replays or sends, in the order it sends them for a selected object.
const hostSession = (): Message[] => [
  { type: "tour", dim: false, spyLit: false },
  { type: "state", picking: false, appRunning: true, targetName: "demo", appName: "Fixture", appPids: [42], hasProject: true, showOtherApps: true, bringToFront: false, basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES], showRefreshCounts: false },
  { type: "roots", nodes: [windowNode] },
  { type: "children", nodeId: "win", nodes: [borderNode], expanded: true },
  { type: "children", nodeId: "border", nodes: [presenterNode], expanded: true },
  { type: "selectionPending", nodeId: "presenter" },
  { type: "selected", nodeId: "presenter", properties: presenterProperties },
  { type: "wpfDetails", nodeId: "presenter", missing: false },
  { type: "definitions", nodeId: "presenter", state: "ready", definitions: [{ kind: "element", qualname: "Page.contentSite", file: "page.py", line: 3, pages: [], pageCount: 1 }] },
  managed(),
  { type: "objectPreview", nodeId: "presenter", reason: "The automation server returned no preview." },
];

describe("Properties sidebar controls", () => {
  it("places the actions after the preview mode and dismisses them after use, Escape, or an outside click", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    const actions = view.doc.querySelector<HTMLDetailsElement>("#sidebar-actions")!;
    expect(actions.parentElement?.classList.contains("sidebar-search-row")).toBe(true);
    expect(actions.previousElementSibling?.classList.contains("sidebar-search")).toBe(true);
    expect(actions.querySelector('.sidebar-actions-menu[role="menu"]')).not.toBeNull();
    for (const [id, message] of [
      ["sidebar-detach", { type: "managedDetach" }],
      ["sidebar-refresh", { type: "managedRefresh" }],
      ["sidebar-export", { type: "managedCopy", kind: "export" }],
    ] as const) {
      actions.open = true;
      view.doc.querySelector<HTMLButtonElement>(`#${id}`)!.click();
      expect(view.posts).toContainEqual(message);
      expect(actions.open).toBe(false);
    }
    actions.open = true;
    actions.querySelector("summary")!.dispatchEvent(new view.dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(actions.open).toBe(false);
    expect(view.doc.activeElement).toBe(actions.querySelector("summary"));
    actions.open = true;
    view.doc.body.click();
    expect(actions.open).toBe(false);
    expect(view.errors).toEqual([]);
  });

  it("labels the search input and keeps the tab selection in sync", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    const search = view.doc.querySelector<HTMLInputElement>("#sidebar-search")!;
    expect(search.getAttribute("aria-label")).toBe("Search");
    expect(search.placeholder).toBe("Search");
    expect(search.parentElement?.querySelector('.codicon-search[aria-hidden="true"]')).not.toBeNull();
    const tabs = [...view.doc.querySelectorAll<HTMLButtonElement>('.sidebar-tabs[role="tablist"] [role="tab"]')];
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
    for (const [index, tab] of tabs.entries()) {
      tab.click();
      expect(tabs.map((item) => item.getAttribute("aria-selected"))).toEqual(tabs.map((_, i) => String(i === index)));
    }
    expect(view.posts).toContainEqual({ type: "managedMethods", action: "activate" });
    expect(view.errors).toEqual([]);
  });
});

describe("Properties sidebar visibility", () => {
  it("shows its placeholder, and nothing else, before anything is selected", () => {
    const view = open("properties-view");
    expect(view.posts).toContainEqual(expect.objectContaining({ type: "propertiesReady" }));
    view.send({ type: "tour", dim: false, spyLit: false }, { type: "state", appRunning: true, hasProject: true }, { type: "roots", nodes: [windowNode] });
    expect(view.hiddenReason("#properties-empty")).toBeUndefined();
    expect(view.text("#properties-empty")).toContain("Select an object to inspect its properties.");
    expect(view.visible("#sidebar-inspector")).toBe(false);
    expect(view.visible("#sidebar-search")).toBe(false);
    // The harness proves a stylesheet rule can hide: the Spy panel's own widgets are not part of the sidebar.
    expect(view.hiddenReason("#tree-pane")).toContain("display:none");
    expect(view.hiddenReason("#properties-pane")).toBeUndefined();
    expect(view.errors).toEqual([]);
  });

  it("shows tabs, search, the mode switch and the rows once a WPF object is selected, with no Description section", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    for (const selector of ["#sidebar-tab-properties", "#sidebar-tab-fields", "#sidebar-tab-methods", "#sidebar-search", "#sidebar-mode", "#sidebar-rows tr[data-name]", "#object-preview"]) {
      expect(view.hiddenReason(selector), selector).toBeUndefined();
    }
    expect(view.visible("#properties-empty")).toBe(false);
    expect(view.doc.querySelector("#sidebar-description, #sidebar-description-content, #sidebar-copy-feedback")).toBeNull();
    expect(view.doc.body.textContent).not.toContain("Select a row to see its description");
    expect(view.names().length).toBeGreaterThan(0);
    expect(view.text("#sidebar-tab-properties")).toBe("Properties");
    expect(view.errors).toEqual([]);
  });

  it("stays visible when the same messages arrive again, as the host replays them to a late view", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    view.send(...hostSession().slice(0, 5), ...hostSession().slice(5));
    expect(view.hiddenReason("#sidebar-search")).toBeUndefined();
    expect(view.hiddenReason("#sidebar-rows tr[data-name]")).toBeUndefined();
    expect(view.errors).toEqual([]);
  });
});

describe("Spy panel visibility", () => {
  it("keeps the tree, selection summary and locator, and points to the sidebar for properties", () => {
    const view = open("spy-view");
    expect(view.posts).toContainEqual(expect.objectContaining({ type: "ready" }));
    expect(view.hiddenReason("#tree-pane")).toBeUndefined();
    expect(view.hiddenReason("#details-empty")).toBeUndefined();
    expect(view.hiddenReason("#properties-elsewhere")).toBeUndefined();
    expect(view.text("#properties-elsewhere")).toContain("Properties are shown in the right sidebar.");
    view.send(...hostSession());
    for (const selector of ["#selection-summary", "#selection-name", "#definitions-group", "#locator-panel", "#generate", "#tree"]) {
      expect(view.hiddenReason(selector), selector).toBeUndefined();
    }
    expect(view.text("#selection-name")).toBe('WPFObject("contentSite")');
    // The sidebar owns the property list and the preview; the panel must not repeat either.
    for (const selector of ["#sidebar-inspector", "#sidebar-search", "#sidebar-rows", "#object-preview", "#preview-element", "#preview-context", "#properties-empty", "#managed-panel", "#property-groups"]) {
      expect(view.visible(selector), selector).toBe(false);
    }
    expect(view.errors).toEqual([]);
  });

  it("hides the properties pane while the sidebar is visible and restores it when it is not", () => {
    const view = open("spy-view");
    view.send({ type: "propertiesVisibility", visible: true });
    expect(view.hiddenReason("#properties-pane")).toContain("hidden");
    expect(view.visible("#properties-elsewhere")).toBe(false);
    view.send({ type: "propertiesVisibility", visible: false });
    expect(view.hiddenReason("#properties-pane")).toBeUndefined();
    expect(view.hiddenReason("#properties-elsewhere")).toBeUndefined();
    expect(view.errors).toEqual([]);
  });
});

describe("Properties sidebar acceptance", () => {
  it("shows aliases and computes ordinals only for loaded WPF siblings", () => {
    const view = open("properties-view");
    const twin = { ...presenterNode, nodeId: "twin" };
    view.send(...hostSession(), { type: "children", nodeId: "border", nodes: [twin, presenterNode], expanded: true }, { type: "selected", nodeId: "presenter", properties: presenterProperties });
    expect(view.names().slice(-5)).toEqual(["ClrClassName", "ClrFullClassName", "WPFControlName", "WPFControlOrdinalNo", "WPFControlText"]);
    expect(view.value("ClrClassName")).toBe("ContentPresenter");
    expect(view.value("WPFControlName")).toBe("contentSite");
    expect(view.value("WPFControlOrdinalNo")).toBe("2");
    const detached = open("properties-view");
    detached.send(basicState, { type: "selected", nodeId: "missing", properties: presenterProperties });
    expect(detached.value("WPFControlOrdinalNo")).toBe("Unknown");
    const forms = open("properties-view");
    forms.send(basicState, { type: "selected", nodeId: "missing", properties: { ...presenterProperties, source: "winforms", properties: { ClrFullClassName: "A.Outer+Inner", ControlName: "button1", WinFormsControlText: "Go" } } });
    expect(forms.value("ClrClassName")).toBe("Inner");
    expect(forms.value("WinFormsControlName")).toBe("button1");
    expect(forms.value("WinFormsControlText")).toBe("Go");
    expect(forms.names()).not.toContain("WPFControlOrdinalNo");
  });

  it("orders window and managed sections and keeps control text out of Extended", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession(), { type: "selected", nodeId: "presenter", properties: { ...presenterProperties, window: { className: "Window" }, properties: { ...presenterProperties.properties, WPFControlText: "Hello" } } });
    expect(view.headings().slice(0, 4)).toEqual(["Standard", "Win32 Window", "Extended", ".NET"]);
    expect(view.names().filter((name) => name === "WPFControlText")).toHaveLength(1);
    const row = view.doc.querySelector('[data-name="WPFControlText"]')!;
    let preceding = row.previousElementSibling;
    while (preceding && !preceding.classList.contains("sidebar-group")) preceding = preceding.previousElementSibling;
    expect(preceding?.textContent).toBe(".NET");
    expect(view.value("WPFControlText")).toBe("Hello");
  });

  it("sorts member blocks, marks kinds, separates headings and persists collapse", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const rows = [
      { member: member("Zoo", { category: "staticProperty" }), value: { status: "ok", kind: "string", scalar: "z" } },
      { member: member("DataContext", { category: "dependencyProperty" }), value: { status: "ok", kind: "object" }, children: [{ member: member("Zed"), value: { status: "ok", kind: "string", scalar: "child" } }] },
      { member: member("DataContextMiddle", { category: "attachedProperty" }), value: { status: "ok", kind: "string", scalar: "a" } },
    ];
    view.send(managed({ sequence: 2, rows }));
    const names = view.names();
    expect(names.slice(names.indexOf("DataContext"), names.indexOf("DataContext") + 3)).toEqual(["DataContext", "DataContext.Zed", "DataContextMiddle"]);
    for (const [name, kind] of [["DataContext", "dependencyProperty"], ["DataContextMiddle", "attachedProperty"], ["Zoo", "staticProperty"]]) {
      expect(view.doc.querySelector(`#sidebar-rows tr[data-name="${name}"] th`)?.getAttribute("data-kind")).toBe(kind);
    }
    expect(tooltip(view, "DataContext")).toContain("Kind: Dependency property");
    const headings = [...view.doc.querySelectorAll("#sidebar-rows tr.sidebar-group")];
    for (const heading of headings.slice(1)) expect(heading.previousElementSibling?.matches('tr.sidebar-gap[aria-hidden="true"]')).toBe(true);
    expect(view.doc.querySelectorAll("#sidebar-rows tr.sidebar-gap")).toHaveLength(headings.length - 1);
    (view.visibleButtons("Standard")[0] as HTMLButtonElement).click();
    const reopened = open("properties-view", view.state()); reopened.send(...hostSession());
    expect(reopened.visibleButtons("Standard")[0].getAttribute("aria-expanded")).toBe("false");
    expect(reopened.names()).not.toContain("Enabled");
    expect(css).toContain('content: "\\25BE"');
    expect(css).toContain('content: "\\25B8"');
  });

  it("3.1 puts the live preview first in the sidebar and keeps it out of the Spy panel", () => {
    const sidebar = open("properties-view");
    expect(sidebar.doc.querySelector(".properties-scroll")?.firstElementChild?.id).toBe("object-preview");
    sidebar.send(...hostSession());
    for (const selector of ["#object-preview", "#preview-element", "#preview-context", "#preview-retry", "#object-preview-status"]) expect(sidebar.hiddenReason(selector), selector).toBeUndefined();
    expect(sidebar.text("#preview-element")).toBe("Element");
    expect(sidebar.text("#preview-context")).toBe("In App context");
    expect(sidebar.text("#object-preview-status")).toContain("no preview");
    const panel = open("spy-view");
    panel.send(...hostSession());
    expect(panel.visible("#object-preview")).toBe(false);
    expect(sidebar.errors.concat(panel.errors)).toEqual([]);
  });

  it("3.2 offers Properties, Fields and Methods tabs and one search box that filters the active tab", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    expect([...view.doc.querySelectorAll("[data-sidebar-tab]")].map((tab) => tab.textContent)).toEqual(["Properties", "Fields", "Methods"]);
    expect(view.doc.querySelectorAll("#sidebar-search")).toHaveLength(1);
    expect(view.doc.querySelectorAll('input[type="search"]:not([hidden])')).toHaveLength(1 + view.doc.querySelectorAll("#search").length);
    const everything = view.names();
    view.type(view.doc.querySelector("#sidebar-search") as HTMLInputElement, "Content");
    const filtered = view.names();
    expect(filtered.length).toBeGreaterThan(0);
    expect(filtered.length).toBeLessThan(everything.length);
    for (const row of view.doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr[data-name]")) expect(row.textContent?.toLowerCase()).toContain("content");
    // Rows from more than one group survive, so the filter spans the groups.
    expect(view.headings().length).toBeGreaterThan(1);
    expect(filtered).toContain("Content");
    expect(filtered).not.toContain("MappedName");
    view.type(view.doc.querySelector("#sidebar-search") as HTMLInputElement, "no-such-row");
    expect(view.names()).toEqual([]);
    expect(view.visible("#sidebar-empty")).toBe(true);
    expect(view.errors).toEqual([]);
  });

  it("3.3 shows the default rows and remembers the choice", () => {
    const basic = ["Enabled", "Height", "Name", "Parent", "Visible", "Width", "ClrClassName", "ClrFullClassName", "WPFControlName", "WPFControlOrdinalNo", "WPFControlText"];
    const view = open("properties-view");
    view.send(...hostSession());
    expect(view.names()).toEqual(basic);
    expect(view.headings()).toEqual(["Standard", ".NET"]);
    expect(view.text("#sidebar-mode-toggle")).toBe("Show all properties");
    expect((view.doc.querySelector("#sidebar-mode") as HTMLInputElement).checked).toBe(false);
    (view.doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
    expect((view.doc.querySelector("#sidebar-mode") as HTMLInputElement).checked).toBe(true);
    expect(view.state()).toMatchObject({ sidebarShowAll: true });
    // A reopened view starts in the remembered mode.
    const reopened = open("properties-view", view.state());
    reopened.send(...hostSession());
    expect((reopened.doc.querySelector("#sidebar-mode") as HTMLInputElement).checked).toBe(true);
    expect(reopened.headings()[0]).toBe("Standard");
    (reopened.doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
    expect((open("properties-view", reopened.state()).doc.querySelector("#sidebar-mode") as HTMLInputElement).checked).toBe(false);
    expect(view.errors.concat(reopened.errors)).toEqual([]);
  });

  it("3.4 groups all properties as Standard, Extended, .NET and UI Automation, with every value once", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    expect(view.headings()).toEqual(["Standard", "Extended", ".NET", "UI Automation"]);
    const names = view.names();
    expect(new Set(names).size).toBe(names.length);
    // Name is the label (the x:Name is its argument), Enabled is IsEnabled, the rectangle rows are Bounds, and the type is shown once.
    for (const duplicate of ["x:Name", "IsEnabled", "Bounds", "Type", "Managed type", "CLR Name", "CLR IsEnabled"]) expect(names, duplicate).not.toContain(duplicate);
    expect(view.value("Name")).toBe('WPFObject("contentSite")');
    expect(names.filter((name) => name === "ClrFullClassName")).toHaveLength(1);
    expect(view.doc.body.textContent?.match(/System\.Windows\.Controls\.ContentPresenter/g)?.length).toBeGreaterThan(0);
    const classCells = [...view.doc.querySelectorAll<HTMLTableCellElement>("#sidebar-rows td")].filter((cell) => cell.textContent === "System.Windows.Controls.ContentPresenter");
    expect(classCells).toHaveLength(1);
    // With Show all properties off there are neither groups nor UI Automation.
    (view.doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
    expect(view.headings()).toEqual(["Standard", ".NET"]);
    expect(view.doc.querySelector("#sidebar-rows")?.textContent).not.toContain("UI Automation");
    expect(view.errors).toEqual([]);
  });

  it("groups categories, names bindings, remembers collapse and filters headings", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const rows = ["typeMetadata", "clrProperty", "dependencyProperty", "attachedProperty", "staticProperty", "event", "style", "resource"].map((category, index) => ({ member: member(index === 0 ? "Name" : `Member${index}`, { category, memberKey: `key${index}` }), value: { status: "ok", kind: "string", scalar: `value${index}` } }));
    view.send(managed({ sequence: 2, rows, bindings: [{ memberKey: "key2", kind: "Binding", status: "active", path: "Title" }], readRemaining: true }));
    expect(view.headings()).toEqual(["Standard", "Extended", ".NET", "Bindings", "Style and template", "Resources", "Events", "UI Automation"]);
    expect(view.names()).toContain("ClrClassName");
    expect([...view.doc.querySelectorAll('[data-name="Member2"] td')].some((cell) => cell.textContent === "Binding; active; Title")).toBe(true);
    (view.visibleButtons("Read remaining")[0] as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "managedReadRemaining" });
    (view.visibleButtons(".NET")[0] as HTMLButtonElement).click();
    expect(view.state()).toMatchObject({ sidebarCollapsed: { ".NET": true } });
    const reopened = open("properties-view", view.state()); reopened.send(...hostSession()); reopened.send(managed({ sequence: 2, rows }));
    expect(reopened.visibleButtons(".NET")[0].getAttribute("aria-expanded")).toBe("false");
    view.type(view.doc.querySelector("#sidebar-search") as HTMLInputElement, "Member7");
    expect(view.headings()).toContain("Resources");
    expect(view.headings()).not.toContain(".NET");
  });

  it("keeps expanded descendants in their root subgroup", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const rows = [{ id: "parent", member: member("Container", { category: "dependencyProperty" }), value: { status: "ok", kind: "object" }, children: [
      { id: "child", member: member("Child", { category: "clrProperty" }), value: { status: "ok", kind: "object" }, children: [
        { member: member("Leaf", { category: "clrField" }), value: { status: "ok", kind: "string", scalar: "nested" } },
      ] },
    ], page: { nextToken: true } }];
    view.send(managed({ sequence: 2, rows }));
    const entries = [...view.doc.querySelectorAll("#sidebar-rows tr")].map((row) => row.classList.contains("sidebar-group") ? row.textContent : row.getAttribute("data-name"));
    const parent = entries.indexOf("Container", entries.indexOf(".NET") + 1);
    expect(entries.slice(parent, parent + 4)).toEqual(["Container", "Container.Child", "Container.Child.Leaf", "Container.Load more"]);
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.names()).not.toContain("Container.Child.Leaf");
    expect(view.errors).toEqual([]);
  });

  it("shows collection items right after their parent, in its sub-group, with Load more and the enumeration error", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const item = (id: string, name: string, value: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({ id, item: true, member: member(`item:${id}`, { name, readable: false, pathSegment: undefined, declaringType: "" }), value, ...extra });
    const rows = [{ id: "parent", member: member("Items", { category: "dependencyProperty" }), value: { status: "ok", kind: "object", runtimeType: "System.Collections.ArrayList" }, itemPage: { nextToken: true }, children: [
      item("count", "Count", { status: "ok", kind: "integer", scalar: 3, runtimeType: "System.Int32" }),
      item("zero", "[0]", { status: "ok", kind: "string", scalar: "first", runtimeType: "System.String" }),
      item("one", "[1]", { status: "ok", kind: "object", runtimeType: "My.Person" }, { children: [{ id: "name", member: member("Name"), value: { status: "ok", kind: "string", scalar: "Ada" } }] }),
      item("boom", "Enumeration threw System.InvalidOperationException: broken", { status: "ok", kind: "unavailable", runtimeType: "" }, { text: "" }),
      { id: "capacity", member: member("Capacity"), value: { status: "ok", kind: "integer", scalar: 4 } },
    ] }];
    view.send(managed({ sequence: 2, rows }));
    const entries = [...view.doc.querySelectorAll("#sidebar-rows tr")].map((row) => row.classList.contains("sidebar-group") ? row.textContent : row.getAttribute("data-name"));
    const parent = entries.indexOf("Items", entries.indexOf(".NET") + 1);
    expect(entries.slice(parent, parent + 8)).toEqual(["Items", "Items.Count", "Items[0]", "Items[1]", "Items[1].Name", "Items.Enumeration threw System.InvalidOperationException: broken", "Items.Load more items", "Items.Capacity"]);
    const cell = (name: string) => view.doc.querySelector(`#sidebar-rows tr[data-name="${name}"] td`)?.textContent;
    expect(cell("Items.Count")).toBe("3");
    expect(cell("Items[0]")).toBe("first");
    expect(cell("Items[1]")).toBe("My.Person");
    (view.visibleButtons("Load more")[0] as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "managedLoadMore", group: "items:parent" });
    expect(view.errors).toEqual([]);
  });

  it("3.4 reports FullName as the label chain from the process, MappedName as the defining element and Parent as a link", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    expect(view.names()).not.toContain("MappedName");
    (view.doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
    expect(view.posts).toContainEqual({ type: "generateLocator", nodeId: "presenter" });
    // The chain is built from the tree, from the process down, and parses back with from_label.
    const chain = 'Process("Fixture.exe").Window("FixtureWindow").WPFObject("Border", "").WPFObject("contentSite")';
    expect(view.value("FullName")).toBe(chain);
    expect(view.value("Parent")).toBe('WPFObject("Border", "")');
    // A suggested locator is a different thing: it does not replace the label chain.
    view.send({ type: "suggestion", nodeId: "presenter", suggestion: { unique: true, strategy: "automationId", helpers: [], window: { code: "Window(title='Fixture')" }, code: "WPFObject('contentSite')" } });
    expect(view.value("FullName")).toBe(chain);
    (view.doc.querySelector('[data-name="Parent"] td button') as HTMLButtonElement).click();
    expect(view.posts).toContainEqual(expect.objectContaining({ type: "select", nodeId: "border" }));
    expect(view.errors).toEqual([]);
  });

  it("3.4 still has Parent and FullName when the sidebar's tree never saw the object", () => {
    const view = open("properties-view");
    // The host sent no tree, only the selection and the ancestors it read with it.
    view.send(basicState, { type: "selected", nodeId: "presenter", properties: presenterProperties });
    expect(view.value("Parent")).toBe('WPFObject("Border", "")');
    (view.doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
    expect(view.value("FullName")).toBe('Process("Fixture.exe").Window("FixtureWindow").WPFObject("Border", "").WPFObject("contentSite")');
    (view.doc.querySelector('[data-name="Parent"] td button') as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "select", nodeId: "border" });
    expect(view.errors).toEqual([]);
  });

  it("shows getter errors in the row", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    view.send(managed({ sequence: 2, rows: [{ member: member("Content"), value: { status: "exception", kind: "unavailable", message: "System.InvalidOperationException", errorMessage: "broken" } }] }));
    expect(view.value("Content")).toBe("Getter threw InvalidOperationException: broken");
  });

  it("copies cells and reads managed rows without a menu", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const row = view.doc.querySelector('[data-name="Content"]') as HTMLTableRowElement;
    (row.cells[0] as HTMLElement).click();
    (row.cells[1] as HTMLElement).click();
    row.querySelector<HTMLButtonElement>('[aria-label="Read again"]')!.click();
    expect(view.posts).toEqual(expect.arrayContaining([{ type: "copy", text: "Content" }, { type: "managedCopy", kind: "value", memberKey: "clr:Content" }, { type: "managedRead", memberKey: "clr:Content" }]));
    expect(view.doc.querySelector("#sidebar-row-menu, .row-menu-button")).toBeNull();
    expect(tooltip(view, "Content")).toContain("Runtime type: System.String");
    expect(view.doc.querySelector('[data-name="Height"] [aria-label="Read again"]')).toBeNull();
    expect(view.headings()).not.toContain("Pinned");
    expect(view.errors).toEqual([]);
  });

  it("groups static fields separately", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    view.send(managed({ sequence: 2, rows: [{ member: member("StaticField", { category: "staticField" }), value: { status: "ok", kind: "string", scalar: "static" } }] }));
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.headings()).toContain("Static fields");
    expect(view.value("StaticField")).toBe("static");
  });

  it("3.7 lists fields with their values on the Fields tab", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.headings()).toEqual(["Instance fields"]);
    expect(view.names()).toEqual(["_count"]);
    expect(view.value("_count")).toBe("7");
    expect(view.visible("#sidebar-mode")).toBe(false);
    expect(view.errors).toEqual([]);
  });

  it("3.8 lists methods with their signatures on the Methods tab", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    (view.doc.querySelector('[data-sidebar-tab="methods"]') as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "managedMethods", action: "activate" });
    view.send(managed({ sequence: 2, methods: { status: "ready", canInvoke: true, items: [{ key: "k", name: "Measure", declaringType: "System.Windows.UIElement", returnType: "System.Void", visibility: "public", isStatic: false, parameters: [{ name: "width", type: "System.Double" }] }] } }));
    expect(view.names()).toEqual(["Measure(System.Double width)"]);
    // The value is the return type and the flags; the declaring type is the tooltip and the description.
    expect(view.value("Measure(System.Double width)")).toBe("System.Void public instance");
    expect(view.doc.querySelector("#sidebar-rows details")).toBeNull();
    expect(view.errors).toEqual([]);
  });

  it("3.9 shows one status line with one Attach button, only while the inspector is not ready, with the real reason", () => {
    const view = open("properties-view");
    view.send(...hostSession().slice(0, 9));
    view.send(managed({ sequence: 2, state: "attach failed", rows: [], failure: { code: "attachFailed", hint: "The target runs elevated." } }));
    expect(view.hiddenReason("#wpf-details-note")).toBeUndefined();
    expect(view.text("#wpf-details-note")).toContain("attachFailed: The target runs elevated.");
    expect(view.visibleButtons("Attach")).toHaveLength(1);
    expect(view.visibleButtons("Attach")[0]?.id).toBe("wpf-details-attach");
    expect(view.visible("#managed-panel")).toBe(false);
    view.send(managed({ sequence: 3 }));
    expect(view.visible("#wpf-details-note")).toBe(false);
    expect(view.visibleButtons("Attach")).toHaveLength(0);
    // The Spy panel never offers attaching from the properties area.
    const panel = open("spy-view");
    panel.send(...hostSession().slice(0, 9));
    panel.send(managed({ sequence: 2, state: "attach failed", rows: [], failure: { code: "attachFailed", hint: "The target runs elevated." } }));
    expect(panel.visibleButtons("Attach")).toHaveLength(0);
    expect(view.errors.concat(panel.errors)).toEqual([]);
  });

  it("3.10 shows the real code and hint, then where to look, never a generic policy sentence", () => {
    const view = open("properties-view");
    view.send(...hostSession().slice(0, 9));
    const header = (failure: { code: string; hint: string }) => failure.code + ": " + failure.hint + " Run `wtk doctor --agent` for details.";
    const failures = [
      { code: "accessDenied", hint: "Check the inspector payload, target permissions, and application compatibility." },
      { code: "blockedByPolicy", hint: "Allow-list the WinTestKit payload directory in your security policy." },
      { code: "workspaceNotTrusted", hint: "Trust this workspace to attach the inspector." },
    ];
    failures.forEach((failure, index) => {
      view.send(managed({ sequence: index + 2, state: "blocked by policy", rows: [], failure }));
      expect(view.text("#sidebar-attach-status")).toBe(header(failure));
      expect(view.text("#wpf-details-note")).not.toContain("administrator");
    });
    // A tree-level block for the selected node says the same, in the same format.
    view.send({ type: "wpfDetails", nodeId: "presenter", missing: false, blocked: failures[1] });
    view.send(managed({ sequence: 9, state: "blocked by policy", rows: [] }));
    expect(view.text("#sidebar-attach-status")).toBe(header(failures[1]));
    expect(view.errors).toEqual([]);
  });
});

const rowsOf = (view: ReturnType<typeof open>) => [...view.doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr.sidebar-row")];
const key = (view: ReturnType<typeof open>, target: Element, init: KeyboardEventInit) => {
  const event = new view.dom.window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
};

describe("Properties sidebar review fixes", () => {
  it("copies UI Automation values and names, with keyboard and interactive children", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const height = view.doc.querySelector('[data-name="Height"]') as HTMLTableRowElement;
    height.cells[0]!.click(); height.cells[1]!.click();
    expect(view.posts).toContainEqual({ type: "copy", text: "Height" });
    expect(view.posts).toContainEqual({ type: "copy", text: height.cells[1]!.textContent });
    expect(view.text("#copy-toast")).toBe("Value copied");
    key(view, height, { key: "Enter" }); key(view, height, { key: "c", ctrlKey: true });
    const before = view.posts.filter((p) => p.type === "copy" || p.type === "managedCopy").length;
    (view.doc.querySelector('[data-name="Parent"] td button') as HTMLButtonElement).click();
    (view.doc.querySelector('[data-name="CLR Parent"] .property-toggle') as HTMLButtonElement).click();
    expect(view.posts.filter((p) => p.type === "copy" || p.type === "managedCopy")).toHaveLength(before);
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "clr:Parent" });
  });

  it("3. shows a value for every .NET row, dependency and attached properties included, or the real reason", () => {
    const dependency = (name: string) => ({ memberKey: `dp:${name}`, name, category: "dependencyProperty", visibility: "public", readable: true, pathSegment: { kind: "dependency", name, ownerType: "System.Windows.Controls.TextBox", ownerAssembly: "PresentationFramework" }, declaringType: "System.Windows.Controls.TextBox", declaredType: "System.Boolean" });
    const attached = (name: string) => ({ ...dependency(name), memberKey: `ap:${name}`, category: "attachedProperty" });
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession().slice(0, 7));
    view.send(managed({
      sequence: 2,
      rows: [
        { member: dependency("AcceptsReturn"), value: { status: "ok", kind: "bool", scalar: false, runtimeType: "System.Boolean", dependencySource: { baseValueSource: "Default" } } },
        { member: attached("Row"), value: { status: "ok", kind: "int", scalar: 3, runtimeType: "System.Int32" } },
        { member: member("Slow"), autoStatus: "timed out" },
        { member: member("SlowToo"), value: { status: "timeout", kind: "unavailable" } },
        { member: member("Throws"), value: { status: "exception", kind: "unavailable", message: "System.InvalidOperationException" } },
        { member: member("Cursor"), value: { status: "redacted", kind: "unavailable", redactionRule: "identity" } },
        { member: member("ApiKey"), value: { status: "redacted", kind: "unavailable", redactionRule: "key" } },
        { member: member("Gone"), autoStatus: "unavailable" },
        { member: member("Later") },
        { member: member("Empty"), value: { status: "ok", kind: "string", scalar: "", runtimeType: "System.String" } },
      ],
    }));
    expect(view.value("AcceptsReturn")).toBe("false");
    expect(view.value("Row")).toBe("3");
    expect(view.value("Slow")).toBe("(timed out)");
    expect(view.value("SlowToo")).toBe("(timed out)");
    expect(view.value("Throws")).toBe("Getter threw InvalidOperationException");
    expect(view.value("Cursor")).toBe("Redacted: element has no automation peer");
    expect(view.value("ApiKey")).toBe("Redacted (rule: key)");
    expect(view.value("Gone")).toBe("(unavailable)");
    expect(view.value("Empty")).toBe('""');
    // Only a row nobody tried to read is "Not read".
    expect(view.value("Later")).toBe("Not read");
    const rows = rowsOf(view).filter((row) => row.dataset.key?.startsWith(".NET/"));
    expect(rows.filter((row) => row.querySelector("td")?.textContent === "Not read")).toHaveLength(1);
    expect(view.errors).toEqual([]);
  });

  it("3. says reading is off when the getters were not allowed, not a bare Not read", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession().slice(0, 7));
    view.send(managed({ sequence: 2, rows: [{ member: member("Content"), autoStatus: "declined" }] }));
    expect(view.value("Content")).toBe("Not read (automatic reading is off)");
  });

  it("4. derives Exists, Left and Top, shows AutomationId as empty, and says when MappedName has no page", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    // The window is at 100,50 on the screen, the presenter at 110,70.
    const win = { ...windowNode, info: { ...windowNode.info, rect: { left: 100, top: 50, width: 500, height: 400 } } };
    const presenter = { ...presenterNode, info: { ...presenterNode.info, rect: { left: 110, top: 70, width: 30, height: 40 } } };
    const properties = { ...presenterProperties, info: presenter.info, ancestors: [win, borderNode] };
    view.send({ type: "roots", nodes: [win] }, { type: "children", nodeId: "win", nodes: [borderNode], expanded: true }, { type: "children", nodeId: "border", nodes: [presenter], expanded: true });
    view.send({ type: "selected", nodeId: "presenter", properties });
    expect(view.value("Exists")).toBe("true");
    expect(view.value("ScreenLeft")).toBe("110");
    expect(view.value("Left")).toBe("10");
    expect(view.value("Top")).toBe("20");
    expect(view.value("AutomationId")).toBe('""');
    // Pages not yet known: the value is not yet known; a finished search with no match says so.
    view.send({ type: "definitions", nodeId: "presenter", state: "ready", definitions: [] });
    expect(view.names()).not.toContain("MappedName");
    // Nothing in this row may still read Unknown for a value the page can derive.
    for (const name of ["Exists", "Left", "Top", "AutomationId"]) expect(view.value(name), name).not.toBe("Unknown");
    // The window itself reports its place on the screen.
    view.send({ type: "selected", nodeId: "win", properties: { ...presenterProperties, info: win.info, ancestors: [] } });
    expect(view.value("Left")).toBe("100");
    expect(view.value("Top")).toBe("50");
    // The meaning is documented in the tooltip of the name.
    expect(tooltip(view, "Left")).toContain("containing window");
    expect(view.errors).toEqual([]);
  });

  it("4. takes AutomationId from the element when the property map has none", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    const { AutomationId, ...rest } = presenterProperties.properties;
    void AutomationId;
    view.send({ type: "selected", nodeId: "presenter", properties: { ...presenterProperties, info: { ...presenterNode.info, automationId: "save" }, properties: rest } });
    expect(view.value("AutomationId")).toBe("save");
    expect(view.names().filter((name) => name === "AutomationId")).toHaveLength(1);
    view.send({ type: "selected", nodeId: "presenter", properties: { ...presenterProperties, properties: rest } });
    expect(view.value("AutomationId")).toBe('""');
  });

  it("5. never runs the refresh walk in the sidebar, and keeps the counts in the Spy panel", () => {
    const drive = (surface: Surface) => {
      const view = open(surface);
      const child = { nodeId: "child", hasChildren: false, info: { controlType: "Button", name: "Save" } };
      view.send({ type: "state", hasProject: true, showRefreshCounts: true }, { type: "roots", nodes: [windowNode] }, { type: "children", nodeId: "win", nodes: [child], expanded: true });
      view.send({ type: "rootsDiff", nodes: [windowNode], revision: 1, refresh: true }, { type: "childrenDiff", nodeId: "win", nodes: [child], revision: 1 });
      return view;
    };
    const panel = drive("spy-view");
    expect(panel.text("#refresh-counts")).toMatch(/^Refresh: \+0 added, -0 removed, \d+ kept, 0 redrawn$/);
    expect(panel.hiddenReason("#refresh-counts")).toBeUndefined();
    const sidebar = drive("properties-view");
    expect(sidebar.text("#refresh-counts")).toBe("");
    expect(sidebar.hiddenReason("#refresh-counts")).toBeDefined();
    expect(panel.errors.concat(sidebar.errors)).toEqual([]);
  });

  it("6. gives the name column room and an ellipsis with a tooltip, and lets values wrap", () => {
    const rule = (selector: string) => css.split("}").find((block) => block.includes(selector)) ?? "";
    const names = rule('.sidebar-table tbody th[scope="row"]');
    expect(rule(".sidebar-table thead th:nth-child(1)")).toMatch(/width:\s*42%/);
    expect(rule(".sidebar-table thead th:nth-child(2)")).toMatch(/width:\s*auto/);
    expect(rule(".sidebar-table thead th:nth-child(3)")).toMatch(/width:\s*28px/);
    expect(names).toMatch(/text-overflow:\s*ellipsis/);
    expect(names).toMatch(/white-space:\s*nowrap/);
    // A name is never broken in the middle of a word; values wrap.
    expect(names).not.toMatch(/overflow-wrap|word-break/);
    expect(rule(".sidebar-table tbody td")).toMatch(/overflow-wrap:\s*anywhere/);
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const head = view.doc.querySelector<HTMLTableCellElement>("#sidebar-table thead th")!;
    expect(head.style.width).toBe("");
    for (const row of rowsOf(view)) expect((row.querySelector("th") as HTMLElement).title.split("\n")[0]).toBe(row.dataset.name);
    expect(view.errors).toEqual([]);
  });

  it("fits visible names and recomputes the limits when the toggle changes", () => {
    const view = open("properties-view");
    const table = view.doc.querySelector<HTMLElement>("#sidebar-table")!;
    const head = table.querySelector<HTMLTableCellElement>("thead th")!;
    let widest = 148;
    Object.defineProperty(table, "clientWidth", { configurable: true, value: 293 });
    Object.defineProperty(view.dom.window.HTMLTableCellElement.prototype, "scrollWidth", {
      configurable: true, get() { return this.matches('tbody th[scope="row"]') ? widest : 0; },
    });
    view.send(...hostSession());
    expect(head.style.width).toBe("50%");
    // The column never shrinks for the same object, so Basic and All keep the Value column where it is.
    widest = 250;
    (view.doc.querySelector("#sidebar-mode") as HTMLElement).click();
    expect(head.style.width).toBe("50%");
    widest = 90;
    (view.doc.querySelector("#sidebar-mode") as HTMLElement).click();
    expect(head.style.width).toBe("50%");
    expect(view.errors).toEqual([]);
  });

  it("7. keeps what a row means as a tooltip on its name: a Standard row's meaning, a member's types, a binding", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    expect(view.doc.querySelector("#sidebar-description")).toBeNull();
    // The name comes first; the name, value and group are on screen already, so the tooltip adds only the rest.
    const content = tooltip(view, "Content").split("\n");
    expect(content[0]).toBe("Content");
    for (const line of ["Declared type: System.Object", "Runtime type: System.String", "Declaring type: System.Windows.Controls.ContentPresenter", "Kind: CLR property"]) expect(content).toContain(line);
    for (const hidden of ["Name: Content", "Value: Hello", "Category: clrProperty", "Group: .NET"]) expect(content).not.toContain(hidden);
    expect(tooltip(view, "Enabled").split("\n")).toEqual(["Enabled", "Whether the control accepts input (UI Automation IsEnabled)."]);
    // A value source and a binding appear when the row has them, and follow the row as values arrive.
    const text = { memberKey: "dp:Text", name: "Text", category: "dependencyProperty", visibility: "public", readable: true, pathSegment: { kind: "dependency", name: "Text", ownerType: "T", ownerAssembly: "A" }, declaringType: "T", declaredType: "System.String" };
    view.send(managed({ sequence: 2, bindings: [{ memberKey: "dp:Text", kind: "Binding", status: "active", path: "Title" }], rows: [{ member: text, value: { status: "ok", kind: "string", scalar: "x", runtimeType: "System.String", dependencySource: { baseValueSource: "Local" } } }] }));
    expect(tooltip(view, "Text")).toContain("Value source: Local");
    expect(tooltip(view, "Text")).toContain("Binding: Binding; active; Title");
    // Clicking a name copies it; it no longer selects a row to describe.
    (view.doc.querySelector('[data-name="Text"] th') as HTMLElement).click();
    expect(view.doc.querySelector('#sidebar-rows [aria-current="true"], #sidebar-rows .described')).toBeNull();
    expect(view.errors).toEqual([]);
  });

  it("7. copies a row clicked on its name cell, through the table body, after a redraw", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    const stale = view.doc.querySelector('[data-name="Name"]') as HTMLElement;
    // A redraw replaces the rows; the handlers belong to the table body, so a click on the new row still counts.
    view.send(managed({ sequence: 2 }));
    expect(stale.isConnected).toBe(false);
    (view.doc.querySelector('[data-name="Name"] th') as HTMLElement).click();
    expect(view.posts).toContainEqual({ type: "copy", text: "Name" });
    expect(view.text("#copy-toast")).toBe("Name copied");
  });

  it("keeps the default rows without row menus or pinned group", () => {
    const view = open("properties-view"); view.send(...hostSession());
    expect(view.names()).not.toContain("MappedName");
    expect(view.headings()).not.toContain("Pinned");
    expect(view.doc.querySelector("#sidebar-row-menu, .row-menu-button")).toBeNull();
  });


});

describe("Properties sidebar attach flow", () => {
  const detachedSnapshot = (sequence: number) => managed({ sequence, state: "detached (idle)", object: undefined, rows: [], methods: { status: "idle", items: [], canInvoke: false } });
  it("3.9 shows one status line with one Attach after Detach and a new selection, and Attach brings the inspector back", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    // Attached: the kebab menu offers Detach and there is no status line.
    expect(view.visible("#sidebar-actions")).toBe(true);
    expect(view.visible("#wpf-details-note")).toBe(false);
    (view.doc.querySelector("#sidebar-actions > summary") as HTMLElement).click();
    expect(view.hiddenReason("#sidebar-detach")).toBeUndefined();
    (view.doc.querySelector("#sidebar-detach") as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "managedDetach" });
    // The host answers with the detached snapshot, then the user selects another object.
    view.send(detachedSnapshot(2));
    view.send({ type: "selectionPending", nodeId: "border" }, { type: "selected", nodeId: "border", properties: { ...presenterProperties, info: borderNode.info, ancestors: [windowNode] } }, { type: "wpfDetails", nodeId: "border", missing: false }, detachedSnapshot(3));
    expect(view.visible("#wpf-details-note")).toBe(true);
    expect(view.text("#sidebar-attach-status")).toBe("detached (idle): The session is detached. Attach again to inspect.");
    expect(view.visibleButtons("Attach")).toHaveLength(1);
    expect(view.visibleButtons("Attach")[0]?.id).toBe("wpf-details-attach");
    expect(view.visible("#managed-panel")).toBe(false);
    expect(view.visible("#sidebar-actions")).toBe(false);
    // The status line stays the only one when the tree reports the same selection again.
    view.send({ type: "wpfDetails", nodeId: "border", missing: false }, detachedSnapshot(4));
    expect(view.doc.querySelectorAll("#wpf-details-note")).toHaveLength(1);
    expect(view.visibleButtons("Attach")).toHaveLength(1);
    expect(view.visible("#wpf-details-note")).toBe(true);
    // Attach asks the host, which answers with a ready snapshot: the line goes and the actions return.
    view.visibleButtons("Attach")[0]!.click();
    expect(view.posts).toContainEqual({ type: "managedAttach" });
    view.send(managed({ sequence: 5 }));
    expect(view.visible("#wpf-details-note")).toBe(false);
    expect(view.visibleButtons("Attach")).toHaveLength(0);
    expect(view.visible("#sidebar-actions")).toBe(true);
    for (const tab of ["properties", "fields", "methods"]) expect(view.visible(`#sidebar-tab-${tab}`), tab).toBe(true);
    expect(view.errors).toEqual([]);
  });

  it("3.9 keeps the same single line when the tree-level notice arrives after the snapshot", () => {
    const view = open("properties-view");
    view.send(...hostSession().slice(0, 7));
    view.send(detachedSnapshot(2));
    // The tree's own "WPF details missing" notice must not add a second line or hide the first.
    view.send({ type: "wpfDetails", nodeId: "presenter", missing: true });
    expect(view.visibleButtons("Attach")).toHaveLength(1);
    expect(view.visible("#wpf-details-note")).toBe(true);
    view.send({ type: "wpfDetails", nodeId: "presenter", missing: false });
    expect(view.visible("#wpf-details-note")).toBe(true);
    expect(view.visibleButtons("Attach")).toHaveLength(1);
    expect(view.errors).toEqual([]);
  });
});

describe("Methods tab invocation", () => {
  const RECORD = "RecordWrite(System.String value, System.Int64 number)";
  const method = (extra: Record<string, unknown> = {}) => ({
    key: "k1", name: "RecordWrite", declaringType: "WinTestKit.Fixture.FixtureControl", returnType: "System.String", visibility: "public", isStatic: false,
    parameters: [{ name: "value", type: "System.String", isOut: false }, { name: "number", type: "System.Int64", isOut: false }], ...extra,
  });
  const snapshot = (items: unknown[], extra: Record<string, unknown> = {}, sequence = 2) => managed({ sequence, methods: { status: "ready", canInvoke: true, items, ...extra } });
  const methodsView = (items: unknown[] = [method()], extra: Record<string, unknown> = {}) => {
    const view = open("properties-view");
    view.send(...hostSession());
    (view.doc.querySelector('[data-sidebar-tab="methods"]') as HTMLButtonElement).click();
    view.send(snapshot(items, extra));
    return view;
  };
  const rowFor = (view: ReturnType<typeof open>, label = RECORD) => view.doc.querySelector(`#sidebar-rows tr.sidebar-row[data-name="${label}"]`) as HTMLTableRowElement;
  const invokeItem = (view: ReturnType<typeof open>, label = RECORD) => {
    return rowFor(view, label).querySelector('[aria-label="Invoke\u2026"]') as HTMLButtonElement;
  };
  const field = (view: ReturnType<typeof open>, index: number) => view.doc.getElementById(`invoke-arg-${index}`) as HTMLInputElement;
  const typeInto = (view: ReturnType<typeof open>, index: number, text: string) => view.type(field(view, index), text);
  const submit = (view: ReturnType<typeof open>) => view.doc.getElementById("invoke-submit") as HTMLButtonElement;
  const forms = (view: ReturnType<typeof open>) => view.doc.querySelectorAll("#sidebar-rows tr.invoke-row");
  const invocations = (view: ReturnType<typeof open>) => view.posts.filter((post) => post.type === "managedInvoke");

  it("offers Invoke\u2026 first in the row menu, enabled when the session can call, the list is ready and the method is supported", () => {
    const view = methodsView();
    const item = invokeItem(view);
    expect(item.disabled).toBe(false);
    expect(item.title).toBe("Invoke\u2026");
    expect(item.querySelector(".codicon-play")).not.toBeNull();
    expect(view.doc.querySelector("#sidebar-rows details")).toBeNull();
    expect(view.errors).toEqual([]);
  });

  it("keeps the item but disables it, with the reason as a tooltip, when invocation cannot work", () => {
    const cases: [string, unknown[], Record<string, unknown>, string][] = [
      ["canInvoke is false", [method()], { canInvoke: false }, "Invocation unavailable: method calls are not enabled for this session (detach, then attach again)"],
      ["the list is loading", [method()], { status: "loading" }, "Invocation unavailable: the method list is not loaded"],
      ["the type is unsupported", [method({ unsupportedReason: "A parameter type is not supported." })], {}, "Invocation unavailable: A parameter type is not supported."],
      ["more than 16 parameters", [method({ parameters: Array.from({ length: 17 }, (_, index) => ({ name: `p${index}`, type: "System.Int32", isOut: false })) })], {}, "Invocation unavailable: more than 16 parameters"],
      ["an out parameter", [method({ parameters: [{ name: "result", type: "System.Int32", isOut: true }] })], {}, "Invocation unavailable: out parameters are not supported"],
    ];
    for (const [name, items, extra, tooltip] of cases) {
      const view = methodsView(items, extra);
      const row = view.doc.querySelector("#sidebar-rows tr.sidebar-row") as HTMLTableRowElement;
      const item = row.querySelector('[aria-label="Invoke\u2026"]') as HTMLButtonElement;
      expect(item.disabled, name).toBe(true);
      expect(item.title, name).toBe(tooltip);
      expect(view.errors).toEqual([]);
    }
  });

  it("shows the Methods value as the return type and flags only, with the rest in the tooltips", () => {
    const view = methodsView([method({ name: "Hidden", visibility: "private", isStatic: true, returnType: "System.Void", parameters: [{ name: "x", type: "App.Thing", isOut: false }], unsupportedReason: "A parameter type is not supported." }), method({ key: "k2", name: "Both", visibility: "protectedInternal", parameters: [] })]);
    const hidden = rowFor(view, "Hidden(App.Thing x)");
    expect((hidden.children[1] as HTMLElement).textContent).toBe("System.Void private static");
    expect((hidden.children[1] as HTMLElement).title).toBe("WinTestKit.Fixture.FixtureControl\nA parameter type is not supported.");
    expect(view.text("#sidebar-rows")).not.toContain("A parameter type is not supported.");
    expect(view.text("#sidebar-rows")).not.toContain("WinTestKit.Fixture.FixtureControl");
    expect(view.value("Both()")).toBe("System.String protected internal instance");
    const description = (hidden.children[0] as HTMLElement).title;
    for (const line of ["Declaring type: WinTestKit.Fixture.FixtureControl", "Returns: System.Void", "Access: private static", "Not supported: A parameter type is not supported.", "Invocation: Invocation unavailable: A parameter type is not supported."]) expect(description).toContain(line);
    expect(view.errors).toEqual([]);
  });

  it("opens an inline form under the method, one labelled input per parameter, and closes it on Cancel", () => {
    const view = methodsView();
    expect(forms(view)).toHaveLength(0);
    invokeItem(view).click();
    expect(view.doc.getElementById("sidebar-row-menu")).toBeNull();
    expect(forms(view)).toHaveLength(1);
    expect(rowFor(view).nextElementSibling).toBe(forms(view)[0]);
    const labels = [...view.doc.querySelectorAll("#sidebar-rows .invoke-field > label[for]")].map((label) => label.textContent);
    expect(labels).toEqual(["value (System.String)", "number (System.Int64)"]);
    expect(view.doc.querySelectorAll("#sidebar-rows .invoke-field input[type=text]")).toHaveLength(2);
    expect(view.doc.querySelector('#sidebar-rows [role="group"]')?.getAttribute("aria-label")).toBe(`Invoke ${RECORD}`);
    expect(view.doc.activeElement).toBe(field(view, 0));
    expect(view.doc.querySelector("#sidebar-rows details")).toBeNull();
    expect([...view.doc.querySelectorAll("#sidebar-rows .invoke-actions button")].map((button) => button.textContent)).toEqual(["Invoke", "Cancel"]);
    (view.doc.getElementById("invoke-cancel") as HTMLButtonElement).click();
    expect(forms(view)).toHaveLength(0);
    expect(view.doc.activeElement).toBe(rowFor(view));
    expect(invocations(view)).toEqual([]);
    expect(view.errors).toEqual([]);
  });

  it("Esc cancels the form from an input and returns focus to the method row", () => {
    const view = methodsView();
    invokeItem(view).click();
    expect(forms(view)).toHaveLength(1);
    expect(key(view, field(view, 0), { key: "Escape" }).defaultPrevented).toBe(true);
    expect(forms(view)).toHaveLength(0);
    expect(view.doc.activeElement).toBe(rowFor(view));
    expect(invocations(view)).toEqual([]);
  });

  it("posts managedInvoke with the typed arguments, as the host expects them", () => {
    const view = methodsView();
    invokeItem(view).click();
    typeInto(view, 0, "hello");
    typeInto(view, 1, "42");
    submit(view).click();
    expect(invocations(view)).toEqual([{ type: "managedInvoke", memberKey: "k1", arguments: [{ kind: "value", text: "hello" }, { kind: "value", text: "42" }] }]);
    // A null string, a boolean, an enum and a floating point number are each their own kind of input.
    const typed = methodsView([method({ key: "k3", name: "Mix", parameters: [{ name: "text", type: "System.String" }, { name: "flag", type: "System.Boolean" }, { name: "mode", type: "App.Mode" }, { name: "ratio", type: "System.Double" }] })]);
    invokeItem(typed, "Mix(System.String text, System.Boolean flag, App.Mode mode, System.Double ratio)").click();
    expect(field(typed, 1).tagName).toBe("SELECT");
    expect(field(typed, 3).inputMode).toBe("decimal");
    expect(field(typed, 2).placeholder).toBe("Enum name or flags");
    typeInto(typed, 0, "ignored");
    const nullBox = typed.doc.getElementById("invoke-null-0") as HTMLInputElement;
    nullBox.checked = true;
    nullBox.dispatchEvent(new typed.dom.window.Event("change", { bubbles: true }));
    expect(field(typed, 0).disabled).toBe(true);
    field(typed, 1).value = "true";
    field(typed, 1).dispatchEvent(new typed.dom.window.Event("change", { bubbles: true }));
    typeInto(typed, 2, "First, Second");
    typeInto(typed, 3, "1.5");
    submit(typed).click();
    expect(invocations(typed)).toEqual([{ type: "managedInvoke", memberKey: "k3", arguments: [{ kind: "null", text: "" }, { kind: "value", text: "true" }, { kind: "enum", text: "First, Second" }, { kind: "value", text: "1.5" }] }]);
    expect(view.errors.concat(typed.errors)).toEqual([]);
  });

  it("submits with Enter in an input, and not while an invocation is in flight", () => {
    const view = methodsView();
    invokeItem(view).click();
    typeInto(view, 0, "x");
    typeInto(view, 1, "1");
    key(view, field(view, 1), { key: "Enter" });
    expect(invocations(view)).toHaveLength(1);
    view.send(snapshot([method()], { invoking: true }, 3));
    expect(submit(view).disabled).toBe(true);
    expect(view.text(".invoke-form")).toContain("Waiting for confirmation or the result\u2026");
    expect(field(view, 0).value).toBe("x");
    key(view, field(view, 1), { key: "Enter" });
    expect(invocations(view)).toHaveLength(1);
    // The host finished (or the user declined the confirmation): the form is still there, ready for another go.
    view.send(snapshot([method()], { invoking: false }, 4));
    expect(submit(view).disabled).toBe(false);
  });

  it("keeps what was typed, and the focus, across the redraws that follow every snapshot", () => {
    const view = methodsView();
    invokeItem(view).click();
    typeInto(view, 0, "abc");
    field(view, 0).setSelectionRange(1, 2);
    view.send(snapshot([method()], {}, 3));
    expect(field(view, 0).value).toBe("abc");
    expect(view.doc.activeElement).toBe(field(view, 0));
    expect([field(view, 0).selectionStart, field(view, 0).selectionEnd]).toEqual([1, 2]);
    expect(forms(view)).toHaveLength(1);
  });

  it("shows the result inline under the row, and in the tooltip of the method", () => {
    const view = methodsView();
    invokeItem(view).click();
    view.send(snapshot([method()], { invocation: { key: "k1", text: "Result: written-1" } }, 3));
    const result = view.doc.querySelector("#sidebar-rows tr.invoke-result") as HTMLElement;
    expect(result.textContent).toBe("Result: written-1");
    expect(result.previousElementSibling).toBe(forms(view)[0]);
    expect(view.doc.querySelector("#sidebar-rows details")).toBeNull();
    // The tooltip of the method's name carries it too.
    expect((rowFor(view).children[0] as HTMLElement).title).toContain("Result: written-1");
    // With the form closed, the result stays directly under the method row.
    key(view, field(view, 0), { key: "Escape" });
    expect(rowFor(view).nextElementSibling?.textContent).toBe("Result: written-1");
    // A failure is shown the same way, and only under the method it belongs to.
    view.send(snapshot([method(), method({ key: "k9", name: "Other", parameters: [] })], { invocation: { key: "k1", text: "Invocation failed or timed out. The method may still have had an effect." } }, 4));
    expect(view.doc.querySelectorAll("#sidebar-rows tr.invoke-result")).toHaveLength(1);
    expect((rowFor(view).children[0] as HTMLElement).title).toContain("Outcome: Invocation failed or timed out.");
    expect(view.errors).toEqual([]);
  });

  it("drops the form when the selection changes or the method disappears", () => {
    const view = methodsView();
    invokeItem(view).click();
    expect(forms(view)).toHaveLength(1);
    view.send(snapshot([method({ key: "other", name: "Another", parameters: [] })], {}, 3));
    expect(forms(view)).toHaveLength(0);
    view.send(snapshot([method()], {}, 4));
    expect(forms(view)).toHaveLength(0);
    invokeItem(view).click();
    view.send({ type: "selectionPending", nodeId: "border" });
    view.send({ type: "selected", nodeId: "border", properties: { ...presenterProperties, info: borderNode.info, ancestors: [windowNode] } });
    view.send(snapshot([method()], {}, 5));
    expect(forms(view)).toHaveLength(0);
  });

  it("opens the invocation form from the play button", () => {
    const view = methodsView(); const button = invokeItem(view); button.focus(); button.click();
    expect(view.doc.activeElement).toBe(field(view, 0)); expect(forms(view)).toHaveLength(1);
  });


});

describe("Not read rows", () => {
  const dotnet = (rows: unknown[], extra: Record<string, unknown> = {}) => managed({ sequence: 2, rows, ...extra });
  const hidden = (name: string, extra: Record<string, unknown> = {}) => ({ ...member(name), visibility: "internal", readable: false, reason: "nonPublic", ...extra });
  const advanced = () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession().slice(0, 7));
    return view;
  };

  it("says why a member cannot be read instead of Not read", () => {
    const view = advanced();
    view.send(dotnet([
      { member: hidden("HasComplexContent") },
      { member: hidden("ContentsChangedHandler", { visibility: "protectedInternal" }) },
      { member: hidden("System.Windows.IContentHost.HostedElements", { visibility: "private" }) },
      { member: hidden("WriteOnlyThing", { visibility: "public", reason: "writeOnly" }) },
      { member: hidden("Item", { visibility: "public", reason: "indexer" }) },
      { member: hidden("Weird", { visibility: "public", reason: "unsupportedType" }) },
      { member: hidden("Twin", { visibility: "public", reason: "ambiguous" }) },
      { member: { ...hidden("NoPath", { visibility: "public", reason: undefined }), pathSegment: undefined } },
      { member: member("Fine"), value: { status: "notReadable", kind: "unavailable" } },
      { member: member("Odd"), value: { status: "unsupported", kind: "unavailable" } },
    ]));
    expect(view.value("HasComplexContent")).toBe("Not readable: internal member, only public members are read");
    expect(view.value("ContentsChangedHandler")).toBe("Not readable: protected internal member, only public members are read");
    expect(view.value("System.Windows.IContentHost.HostedElements")).toBe("Not readable: private member, only public members are read");
    expect(view.value("WriteOnlyThing")).toBe("Not readable: write-only property");
    expect(view.value("Item")).toBe("Not readable: indexer, it needs arguments");
    expect(view.value("Weird")).toBe("Not readable: its type is not supported");
    expect(view.value("Twin")).toBe("Not readable: the name matches more than one member");
    expect(view.value("NoPath")).toBe("Not readable: the member has no read path");
    expect(view.value("Fine")).toBe("Not readable: the inspector cannot read this member");
    expect(view.value("Odd")).toBe("Not readable: its type is not supported");
    expect(view.errors).toEqual([]);
  });

  it("leaves no .NET row of a TextBlock-sized object bare Not read once the automatic read has run", () => {
    const view = advanced();
    const unreadable = Array.from({ length: 40 }, (_, index) => ({ member: hidden(`Internal${index}`) }));
    const readable = Array.from({ length: 20 }, (_, index) => ({ member: member(`Public${index}`), value: { status: "ok", kind: "string", scalar: `v${index}`, runtimeType: "System.String" } }));
    const outcomes = [{ member: member("Slow"), autoStatus: "timed out" }, { member: member("Throws"), value: { status: "exception", kind: "unavailable", message: "System.InvalidOperationException" } }];
    const typeFact = { member: { ...member("FullName"), category: "typeMetadata", pathSegment: { kind: "type", name: "FullName" } }, value: { status: "ok", kind: "string", scalar: "System.Windows.Controls.TextBlock", runtimeType: "System.String" } };
    view.send(dotnet([...unreadable, ...readable, ...outcomes, typeFact]));
    const cells = [...view.doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr.sidebar-row")].filter((row) => row.dataset.key?.startsWith(".NET/")).map((row) => row.children[1]?.textContent);
    // The type fact supplies the class name without a duplicate row.
    expect(cells.length).toBe(67);
    expect(cells.filter((text) => text === "Not read")).toEqual([]);
    expect(cells.filter((text) => text?.startsWith("Not readable: "))).toHaveLength(40);
    // Declined consent changes nothing for rows that could never be read; the readable ones say reading is off.
    view.send(dotnet([{ member: hidden("HasComplexContent"), autoStatus: "declined" }, { member: member("Text"), autoStatus: "declined" }], { sequence: 3 }));
    expect(view.value("HasComplexContent")).toBe("Not readable: internal member, only public members are read");
    expect(view.value("Text")).toBe("Not read (automatic reading is off)");
  });
});

describe("Win32 window rows", () => {
  const dialog = { nodeId: "dlg", source: "uia", hasChildren: true, info: { controlType: "Window", name: "Open", className: "#32770", frameworkId: "Win32", nativeWindowHandle: 66000, processId: 7 } };
  const edit = { nodeId: "edit", source: "uia", hasChildren: false, info: { controlType: "Edit", name: "", className: "Edit", frameworkId: "Win32", nativeWindowHandle: 199242, processId: 7, isEnabled: true, isOffscreen: false, rect: { left: 10, top: 20, width: 300, height: 200 } } };
  const facts = {
    handle: 199242, className: "Edit", text: "hello",
    styles: [{ name: "WS_CHILD", value: 0x40000000 }, { name: "WS_VISIBLE", value: 0x10000000 }, { name: "ES_LEFT", value: 0 }, { name: "ES_MULTILINE", value: 4 }],
    rawStyle: 0x50000004, unknownStyle: 0x100,
    exStyles: [{ name: "WS_EX_CLIENTEDGE", value: 0x200 }], rawExStyle: 0x200,
    controlId: 15, processId: 7, threadId: 9, owner: 0, parent: 66000,
    rect: { left: 10, top: 20, width: 300, height: 200 }, clientRect: { left: 0, top: 0, width: 296, height: 196 },
    visible: true, enabled: true, topmost: false, dpi: 96,
  };
  const session = (properties: Record<string, unknown>): Message[] => [
    { type: "tour", dim: false, spyLit: false },
    { type: "state", picking: false, appRunning: true, targetName: "demo", appName: "Fixture", appPids: [7], hasProject: true, showOtherApps: true, bringToFront: false, basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES], showRefreshCounts: false },
    { type: "roots", nodes: [dialog] },
    { type: "children", nodeId: "dlg", nodes: [edit], expanded: true },
    { type: "selectionPending", nodeId: "edit" },
    { type: "selected", nodeId: "edit", properties: { info: edit.info, properties: { Name: "" }, ancestors: [dialog], ...properties } },
  ];
  const fullUia = { info: edit.info, properties: { Name: "", ClassName: "Edit", ProcessId: "7", NativeWindowHandle: "199242", HelpText: "Type here" }, ancestors: [dialog], inspection: [], window: facts };

  it("shows the window class, control ID, text, handle and styles with Show all properties off", () => {
    const view = open("properties-view");
    view.send(...session({ window: facts }));
    expect(view.headings()).toEqual(["Standard", "Win32 Window"]);
    expect(view.names()).toEqual(expect.arrayContaining(["Window Class", "Control ID", "Text", "Handle", "Styles"]));
    expect(view.value("Window Class")).toBe("Edit");
    expect(view.value("Control ID")).toBe("15 (0xF)");
    expect(view.value("Text")).toBe("hello");
    expect(view.value("Handle")).toBe("0x00030A4A (199242)");
    expect(view.value("Styles")).toBe("WS_CHILD | WS_VISIBLE | ES_LEFT | ES_MULTILINE | 0x00000100");
    // The raw values and the process facts belong to the Advanced view.
    expect(view.names()).not.toContain("Raw Style");
    expect(view.names()).not.toContain("Thread ID");
    // The button and its status text are gone: everything loads with the selection.
    expect(view.doc.querySelector("#load-properties")).toBeNull();
    expect(view.doc.querySelector("#properties-status")).toBeNull();
    expect(view.doc.body.textContent).not.toContain("Load all properties");
    expect(view.errors).toEqual([]);
  });

  it("lists every window fact once under Win32 Window with Show all properties on", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...session({ window: facts }), { type: "allProperties", nodeId: "edit", properties: fullUia });
    expect(view.headings()).toContain("Win32 Window");
    expect(view.value("Raw Style")).toBe("0x50000004");
    expect(view.value("Extended Styles")).toBe("WS_EX_CLIENTEDGE");
    expect(view.value("Raw Extended Style")).toBe("0x00000200");
    expect(view.value("Process ID")).toBe("7");
    expect(view.value("Thread ID")).toBe("9");
    expect(view.value("Owner Window")).toBe("None");
    expect(view.value("Parent Window")).toBe("0x000101D0 (66000)");
    expect(view.value("Window Rect")).toBe("10, 20, 300 × 200");
    expect(view.value("Client Rect")).toBe("0, 0, 296 × 196");
    expect(view.value("Window Visible")).toBe("true");
    expect(view.value("Window Enabled")).toBe("true");
    expect(view.value("Topmost")).toBe("false");
    expect(view.value("DPI")).toBe("96");
    // The complete UI Automation list arrived without a button, minus what the window rows already say.
    expect(view.value("HelpText")).toBe("Type here");
    for (const repeated of ["ClassName", "ProcessId", "NativeWindowHandle"]) expect(view.names(), repeated).not.toContain(repeated);
    const all = view.names();
    expect(new Set(all).size).toBe(all.length);
    expect(view.errors).toEqual([]);
  });

  it("lists the bits each style stands for in its tooltip and copies from the row", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...session({ window: facts }));
    const row = view.doc.querySelector('#sidebar-rows [data-name="Styles"]') as HTMLTableRowElement;
    const description = (row.cells[0] as HTMLElement).title;
    expect(description).toContain("WS_CHILD: 0x40000000");
    expect(description).toContain("ES_MULTILINE: 0x00000004");
    expect(description).toContain("Unnamed bits: 0x00000100");
    row.cells[1]!.click(); row.cells[0]!.click();
    expect(view.posts).toEqual(expect.arrayContaining([
      { type: "copy", text: "WS_CHILD | WS_VISIBLE | ES_LEFT | ES_MULTILINE | 0x00000100" },
      { type: "copy", text: "Styles" },
    ]));
    expect(view.errors).toEqual([]);
  });

  it("shows no window rows for a node without a native window and keeps its UI Automation rows", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...session({}), { type: "allProperties", nodeId: "edit", properties: { ...fullUia, window: undefined } });
    expect(view.headings()).not.toContain("Win32 Window");
    for (const name of ["Window Class", "Handle", "Styles"]) expect(view.names()).not.toContain(name);
    expect(view.names()).toEqual(expect.arrayContaining(["ClassName", "ProcessId", "NativeWindowHandle", "HelpText"]));
    expect(view.errors).toEqual([]);
  });

  it("omits what the system would not answer and never invents a control ID", () => {
    const view = open("properties-view");
    const partial: Record<string, unknown> = { ...facts };
    delete partial.text;
    delete partial.controlId;
    view.send(...session({ window: partial }));
    expect(view.names()).toEqual(expect.arrayContaining(["Window Class", "Handle", "Styles"]));
    expect(view.names()).not.toContain("Text");
    expect(view.names()).not.toContain("Control ID");
    expect(view.errors).toEqual([]);
  });

  it("says the rest is loading while it reads, then clears the message", () => {
    const view = open("properties-view");
    view.send(...session({ window: facts }));
    expect(view.visible("#properties-view-status")).toBe(false);
    view.send({ type: "propertiesLoading", nodeId: "edit", loading: true });
    expect(view.visible("#properties-view-status")).toBe(true);
    expect(view.text("#properties-view-status")).toContain("Reading all UI Automation properties");
    view.send({ type: "allProperties", nodeId: "edit", properties: fullUia }, { type: "propertiesLoading", nodeId: "edit", loading: false });
    expect(view.visible("#properties-view-status")).toBe(false);
    // A result for another object changes nothing.
    view.send({ type: "propertiesLoading", nodeId: "other", loading: true });
    expect(view.visible("#properties-view-status")).toBe(false);
    expect(view.errors).toEqual([]);
  });

  it("never asks the host to load properties: the panel has no such request", () => {
    const view = open("properties-view");
    view.send(...session({ window: facts }));
    expect(view.posts.some((post) => post.type === "loadProperties")).toBe(false);
  });
});

describe("Properties sidebar for a WinForms object", () => {
  const formNode = { nodeId: "form", source: "winforms", hasChildren: true, info: { controlType: "Window", name: "WinForms Fixture", className: "WindowsForms10.Window.8.app.0.1", processId: 42, frameworkId: "WinForm" } };
  const buttonNode = {
    nodeId: "winforms:button", source: "winforms", hasChildren: false,
    info: { controlType: "Button", name: "OK", className: "System.Windows.Forms.Button", isEnabled: true, isOffscreen: false, frameworkId: "WinForms", rect: { left: 10, top: 20, width: 75, height: 23 } },
    identity: { type: "System.Windows.Forms.Button", xName: "button1", automationId: "button1" },
  };
  const buttonProperties = {
    source: "winforms",
    info: buttonNode.info,
    ancestors: [formNode],
    uiaMapped: true,
    properties: {
      ClrFullClassName: "System.Windows.Forms.Button", ControlName: "button1", AutomationId: "button1", Name: "OK", ControlType: "Button",
      Bounds: "{left:10}", Visible: "True", IsEnabled: "True", HasKeyboardFocus: "False", ProcessId: "42", WindowHandle: "7", WinFormsControlText: "OK",
    },
    uia: { properties: { ClassName: "WindowsForms10.BUTTON.app.0.1", FrameworkId: "WinForm" }, inspection: [] },
  };
  const winformsMember = (name: string, extra: Record<string, unknown> = {}) => ({
    memberKey: "clr:" + name, name, category: "clrProperty", visibility: "public", readable: true,
    pathSegment: { kind: "property", name }, declaringType: "System.Windows.Forms.Control", declaredType: "System.String", ...extra,
  });
  const session = (): Message[] => [
    { type: "tour", dim: false, spyLit: false },
    { type: "state", picking: false, appRunning: true, targetName: "demo", appName: "Fixture", appPids: [42], hasProject: true, showOtherApps: true, bringToFront: false, basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES], showRefreshCounts: false },
    { type: "roots", nodes: [formNode] },
    { type: "children", nodeId: "form", nodes: [buttonNode], expanded: true },
    { type: "selectionPending", nodeId: "winforms:button" },
    { type: "selected", nodeId: "winforms:button", properties: buttonProperties },
    { type: "wpfDetails", nodeId: "winforms:button", missing: false },
    {
      type: "managedPanel", sequence: 1, visible: true, state: "ready",
      object: { objectId: "o", type: { fullName: "System.Windows.Forms.Button", assemblyName: "System.Windows.Forms", baseTypes: ["System.Windows.Forms.ButtonBase", "System.Windows.Forms.Control"] } },
      rows: [
        { member: winformsMember("Text"), value: { status: "ok", kind: "string", scalar: "OK", runtimeType: "System.String" } },
        { member: winformsMember("Name"), value: { status: "ok", kind: "string", scalar: "button1", runtimeType: "System.String" } },
        { member: { ...winformsMember("clicks", { category: "clrField", visibility: "private", readable: false, reason: "nonPublic" }), pathSegment: { kind: "field", name: "clicks", memberKey: "clrField|clicks", declaringType: "Fixture.Form" } }, value: { status: "ok", kind: "integer", scalar: 3, runtimeType: "System.Int32" } },
      ],
    },
  ];

  it("labels the row WinFormsObject with the control name and shows the WinForms badge", () => {
    const view = open("spy-view");
    view.send(...session());
    const row = view.doc.querySelector('[data-node-id="winforms:button"]')!;
    expect(row.getAttribute("aria-label")).toBe('WinFormsObject("button1")');
    expect(row.querySelector(".technology-badge")?.textContent).toBe("WinForms");
    expect(view.doc.querySelector('[data-node-id="form"] .technology-badge')?.textContent).toBe("WinForms");
    expect(view.errors).toEqual([]);
  });

  it("shows the Name row as the control name and the managed rows on the Properties, Fields and Methods tabs", () => {
    const view = open("properties-view");
    view.send(...session());
    for (const selector of ["#sidebar-tab-properties", "#sidebar-tab-fields", "#sidebar-tab-methods", "#sidebar-search", "#sidebar-mode"]) expect(view.hiddenReason(selector), selector).toBeUndefined();
    expect(view.value("Name")).toBe("button1");
    expect(view.value("ClrFullClassName")).toBe("System.Windows.Forms.Button");
    expect(view.value("WinFormsControlText")).toBe("OK");
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.names()).toEqual(["clicks"]);
    expect(view.value("clicks")).toBe("3");
    (view.doc.querySelector('[data-sidebar-tab="methods"]') as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "managedMethods", action: "activate" });
    expect(view.errors).toEqual([]);
  });

  it("names the section WinForms and lists the control name in it", () => {
    const view = open("spy-view");
    view.send(...session());
    expect(view.doc.querySelector<HTMLElement>("#wpf-section")?.hidden).toBe(false);
    expect(view.text("#wpf-section h3")).toBe("WinForms");
    expect(view.doc.querySelector("#wpf-properties")?.textContent).toContain("button1");
    expect(view.errors).toEqual([]);
  });
});

describe("Binding details in the Properties sidebar", () => {
  const text = (scalar: string) => ({ status: "ok", kind: "string", declaredType: "System.Object", runtimeType: "System.String", scalar });
  const handle = (objectId: string) => ({ status: "ok", kind: "object", declaredType: "System.Object", runtimeType: "App.Source", object: { objectId, generation: 1 } });
  const dependency = { member: member("Text", { category: "dependencyProperty", memberKey: "dp:Text" }), value: text("shown") };
  const single = {
    memberKey: "dp:Text", kind: "binding", status: "Active", mode: "TwoWay", updateSourceTrigger: "PropertyChanged", path: "Name", elementName: "Source", sourceType: "App.Source", converterType: "App.Converter",
    relativeSource: { mode: "FindAncestor", ancestorType: "App.Host", ancestorLevel: 2 }, converterParameter: handle("param"), converterCulture: "", stringFormat: "{0:N2}", fallbackValue: text("fb"), targetNullValue: text("none"),
    delay: 250, bindingGroupName: "group", xPath: "item", isAsync: false, notifyOnSourceUpdated: true, notifyOnTargetUpdated: false, validatesOnDataErrors: true, validatesOnExceptions: false, validatesOnNotifyDataErrors: true,
    validationRules: ["App.Rule"], hasUpdateSourceExceptionFilter: true, dataItem: handle("item"), resolvedSource: handle("source"), resolvedSourcePropertyName: "Name", hasError: true, hasValidationError: false, validationErrors: ["System.FormatException"],
  };
  const objectRow = (field: string, label: string, objectId: string, path: number[] = [], extra: Record<string, unknown> = {}) => ({ id: "row-" + field + path.join(""), item: true, binding: { memberKey: "dp:Text", path, field }, member: member(label, { memberKey: `binding:${field}${path.join("")}`, category: "dependencyProperty", readable: false, pathSegment: undefined }), value: handle(objectId), ...extra });
  const show = (bindings: unknown[], bindingObjects: unknown[] = []) => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    view.send(managed({ sequence: 2, rows: [dependency], bindings, bindingObjects }));
    return view;
  };
  const bindingRow = (view: ReturnType<typeof open>) => view.doc.querySelector<HTMLElement>('tr[data-key="Bindings/Text"]')!;
  const toggle = (row: Element | null) => row!.querySelector<HTMLButtonElement>("button.property-toggle")!;
  const detailNames = (view: ReturnType<typeof open>) => view.names().filter((name) => name!.startsWith("Text."));

  it("shows one collapsed row per binding, named by the property, with kind, status and path", () => {
    const view = show([single]);
    expect(bindingRow(view).querySelector("td")?.textContent).toBe("binding; Active; Name");
    expect(toggle(bindingRow(view)).getAttribute("aria-expanded")).toBe("false");
    expect(detailNames(view)).toEqual([]);
    expect(view.errors).toEqual([]);
  });

  it("opens to the details, leaves out empty and default fields, and closes again", () => {
    const view = show([single], [objectRow("converterParameter", "ConverterParameter", "param"), objectRow("dataItem", "DataItem", "item"), objectRow("resolvedSource", "ResolvedSource", "source")]);
    toggle(bindingRow(view)).click();
    expect(toggle(bindingRow(view)).getAttribute("aria-expanded")).toBe("true");
    const rows = Object.fromEntries(detailNames(view).map((name) => [name!.slice(5), view.value(name!)]));
    expect(rows).toEqual({
      Mode: "TwoWay", UpdateSourceTrigger: "PropertyChanged", Path: "Name", XPath: "item", ElementName: "Source",
      RelativeSource: "FindAncestor; App.Host; level 2", Source: "App.Source", Converter: "App.Converter", ConverterParameter: "App.Source", ConverterCulture: "(invariant)",
      StringFormat: "{0:N2}", FallbackValue: "fb", TargetNullValue: "none", Delay: "250 ms", BindingGroupName: "group",
      NotifyOnSourceUpdated: "true", ValidatesOnDataErrors: "true", ValidationRules: "App.Rule", UpdateSourceExceptionFilter: "set",
      DataItem: "App.Source", ResolvedSource: "App.Source", ResolvedSourcePropertyName: "Name", HasError: "true", Error: "System.FormatException",
    });
    // Omitted: false flags, ValidatesOnNotifyDataErrors while true, HasValidationError while false, Delay of 0, empty strings.
    for (const omitted of ["IsAsync", "NotifyOnTargetUpdated", "ValidatesOnExceptions", "ValidatesOnNotifyDataErrors", "HasValidationError"]) expect(view.names()).not.toContain("Text." + omitted);
    toggle(bindingRow(view)).click();
    expect(detailNames(view)).toEqual([]);
    expect(view.errors).toEqual([]);
  });

  it("expands and collapses a binding with its arrow", () => {
    const view = show([single]); const button = toggle(bindingRow(view));
    expect(button.getAttribute("aria-expanded")).toBe("false"); button.click();
    expect(toggle(bindingRow(view)).getAttribute("aria-expanded")).toBe("true"); toggle(bindingRow(view)).click();
  });

  it("expands DataItem and ResolvedSource through the existing expand flow and lists their members below", () => {
    const item = objectRow("dataItem", "DataItem", "item");
    const view = show([single], [item, objectRow("resolvedSource", "ResolvedSource", "source")]);
    toggle(bindingRow(view)).click();
    const row = view.doc.querySelector<HTMLElement>('#sidebar-rows [data-name="Text.DataItem"]')!;
    toggle(row).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: item.member.memberKey, scope: "bindings" });
    // The host answers with the object's members; they appear under the row, expandable in their own scope.
    const child = { id: "child", member: member("Name", { memberKey: "clr:Name" }), value: text("inner") };
    view.send(managed({ sequence: 3, rows: [dependency], bindings: [single], bindingObjects: [{ ...item, children: [child, { id: "nested", member: member("Parent", { memberKey: "clr:Parent" }), value: handle("parent") }] }, objectRow("resolvedSource", "ResolvedSource", "source")] }));
    expect(view.value("Text.DataItem.Name")).toBe("inner");
    expect(view.names()).toContain("Text.DataItem.Parent");
    toggle(view.doc.querySelector('#sidebar-rows [data-name="Text.DataItem.Parent"]')).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "clr:Parent", scope: "row-dataItem" });
    expect(view.errors).toEqual([]);
  });

  it("nests the child bindings of Multi- and PriorityBindings, each opening on its own", () => {
    const child = (path: string) => ({ memberKey: "dp:Text", kind: "binding", status: "Active", mode: "OneWay", updateSourceTrigger: "Default", path, dataItem: handle("d" + path), resolvedSourcePropertyName: path });
    const multi = { memberKey: "dp:Text", kind: "multiBinding", status: "Active", mode: "Default", updateSourceTrigger: "Default", converterType: "App.Join", activeChildIndex: 1, children: [child("First"), child("Second")] };
    const view = show([multi], [objectRow("dataItem", "DataItem", "dFirst", [0]), objectRow("dataItem", "DataItem", "dSecond", [1])]);
    toggle(bindingRow(view)).click();
    expect(detailNames(view)).toEqual(expect.arrayContaining(["Text.Converter", "Text.ActiveBinding", "Text.Bindings[0]", "Text.Bindings[1]"]));
    expect(view.value("Text.ActiveBinding")).toBe("child 1");
    expect(view.value("Text.Bindings[1]")).toBe("binding; Active; Second");
    expect(view.names()).not.toContain("Text.Bindings[1].Path");
    toggle(view.doc.querySelector('#sidebar-rows [data-name="Text.Bindings[1]"]')).click();
    expect(view.value("Text.Bindings[1].Path")).toBe("Second");
    expect(view.value("Text.Bindings[1].DataItem")).toBe("App.Source");
    expect(view.names()).not.toContain("Text.Bindings[0].Path");
    // Each child's object row belongs to that child.
    toggle(view.doc.querySelector('#sidebar-rows [data-name="Text.Bindings[1].DataItem"]')).click();
    expect(view.posts).toContainEqual(expect.objectContaining({ type: "managedExpand", scope: "bindings", memberKey: "binding:dataItem1" }));
    expect(view.errors).toEqual([]);
  });

  it("shows a binding value that is not an object as text", () => {
    const redacted = { status: "redacted", kind: "unavailable", redactionRule: "password" };
    const view = show([{ ...single, fallbackValue: redacted, dataItem: undefined, resolvedSource: undefined, converterParameter: undefined }]);
    toggle(bindingRow(view)).click();
    expect(view.value("Text.FallbackValue")).toContain("Redacted");
    expect(view.names()).not.toContain("Text.DataItem");
  });

  it("starts closed again for another object", () => {
    const view = show([single]);
    toggle(bindingRow(view)).click();
    expect(detailNames(view).length).toBeGreaterThan(0);
    view.send({ type: "selected", nodeId: "border", properties: { ...presenterProperties, info: borderNode.info } });
    view.send({ type: "selected", nodeId: "presenter", properties: presenterProperties });
    view.send(managed({ sequence: 5, rows: [dependency], bindings: [single] }));
    expect(detailNames(view)).toEqual([]);
  });
});

describe("Style, templates and resources in the Properties sidebar", () => {
  const text = (scalar: string) => ({ status: "ok", kind: "string", declaredType: "System.Object", runtimeType: "System.String", scalar });
  const handle = (objectId: string, runtimeType = "System.Windows.Media.SolidColorBrush") => ({ status: "ok", kind: "object", declaredType: "System.Object", runtimeType, object: { objectId, generation: 1 } });
  const flag = (scalar: boolean) => ({ status: "ok", kind: "boolean", declaredType: "System.Object", runtimeType: "System.Boolean", scalar });
  const setter = (property: string, extra: Record<string, unknown> = {}) => ({ property, owner: "System.Windows.Controls.Control", kind: "value", ...extra });
  const trigger = (extra: Record<string, unknown> = {}) => ({ kind: "trigger", active: "active", conditions: [], setterCount: 0, settersTruncated: false, setters: [], enterActions: 0, exitActions: 0, ...extra });
  const level = (extra: Record<string, unknown> = {}) => ({ setterCount: 0, settersTruncated: false, setters: [], triggerCount: 0, triggersTruncated: false, triggers: [], ...extra });
  const template = (extra: Record<string, unknown> = {}) => ({ kind: "controlTemplate", triggerCount: 0, triggersTruncated: false, triggers: [], partsTruncated: false, parts: [], ...extra });
  const dictionary = (extra: Record<string, unknown> = {}) => ({ count: 0, truncated: false, entries: [], mergedTruncated: false, mergedDictionaries: [], ...extra });
  const slotRow = (slot: string, objectId: string, label: string, runtimeType?: string, extra: Record<string, unknown> = {}) => ({ id: "row-" + objectId, item: true, styling: { slot }, member: member(label, { memberKey: "styling:" + objectId, readable: false, pathSegment: undefined }), value: handle(objectId, runtimeType), ...extra });
  const resourceRow = (slot: string, objectId: string, key: string, extra: Record<string, unknown> = {}) => ({ id: "row-" + objectId, item: true, text: "(expand to read)", styling: { slot }, member: member(key, { memberKey: "styling:" + objectId, readable: false, pathSegment: undefined }), ...extra });
  const styling = {
    applicable: true,
    style: {
      source: "local", key: "Fancy", targetType: "System.Windows.Controls.Button",
      ...level({
        setterCount: 3, setters: [setter("Padding", { value: text("4,4,4,4") }), setter("Foreground", { kind: "dynamicResource", expression: "Accent" }), setter("Tag", { kind: "value", value: handle("tag", "App.Marker") })],
        triggerCount: 2, triggers: [
          trigger({ kind: "trigger", active: "inactive", conditions: [{ property: "System.Windows.UIElement.IsEnabled", value: flag(false), active: "inactive" }], setterCount: 1, setters: [setter("Opacity", { owner: "System.Windows.UIElement", value: text("0.5") })] }),
          trigger({ kind: "dataTrigger", active: "unknown", conditions: [{ binding: "Path=Ready", value: flag(true), active: "unknown" }] }),
        ],
      }),
      basedOn: [{ key: "Base", targetType: "System.Windows.Controls.Button", ...level({ setterCount: 1, setters: [setter("Margin", { value: text("2") })] }) }],
      basedOnTruncated: false,
    },
    templates: {
      controlTemplate: template({ targetType: "System.Windows.Controls.Button", rootType: "System.Windows.Controls.Border", parts: [{ name: "PART_Border", type: "System.Windows.Controls.Border", element: handle("border", "System.Windows.Controls.Border") }], triggerCount: 1, triggers: [trigger({ active: "unknown", conditions: [{ property: "System.Windows.UIElement.Opacity", sourceName: "PART_Border", value: text("1"), active: "unknown" }] })] }),
      itemTemplate: template({ kind: "dataTemplate", dataType: "App.Person" }),
      itemsPanel: template({ kind: "itemsPanelTemplate", rootType: "System.Windows.Controls.WrapPanel" }),
      itemContainerStyle: { source: "local", targetType: "System.Windows.Controls.ListBoxItem", ...level({ setterCount: 1, setters: [setter("Padding", { value: text("3") })] }), basedOn: [], basedOnTruncated: false },
      templatedParent: handle("parent", "System.Windows.Controls.Button"),
    },
    resources: dictionary({
      count: 3, entries: [
        { key: "Title", keyKind: "string", index: 0 },
        { key: "Accent", keyKind: "string", index: 1 },
        { key: "System.Windows.Controls.Button", keyKind: "type", index: 2 },
      ],
      mergedDictionaries: [{ source: "Themes/Dark.xaml", count: 12 }, { count: 0 }],
    }),
    application: dictionary({ count: 250, truncated: true, entries: [{ key: "AppTitle", keyKind: "string", index: 0 }] }),
  };
  const objects = [
    slotRow("style.setters.2.value", "tag", "value", "App.Marker"),
    slotRow("templates.controlTemplate.parts.0.element", "border", "element", "System.Windows.Controls.Border"),
    slotRow("templates.templatedParent", "parent", "templatedParent", "System.Windows.Controls.Button"),
    // A resource has a row from the start, without a value: it is read when the row is expanded.
    resourceRow("resources.entries.0", "title", "Title"),
    resourceRow("resources.entries.1", "accent", "Accent"),
    resourceRow("resources.entries.2", "button-style", "System.Windows.Controls.Button"),
    resourceRow("application.entries.0", "app-title", "AppTitle"),
  ];
  const show = (result: unknown = styling, stylingObjects: unknown[] = objects) => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    view.send(managed({ sequence: 2, styling: result, stylingObjects }));
    return view;
  };
  const row = (view: ReturnType<typeof open>, name: string) => view.doc.querySelector<HTMLElement>(`#sidebar-rows [data-name="${name}"]`);
  const toggle = (element: Element | null) => element!.querySelector<HTMLButtonElement>("button.property-toggle")!;
  const subgroups = (view: ReturnType<typeof open>) => [...view.doc.querySelectorAll("#sidebar-rows tr.sidebar-group")].map((item) => item.textContent);
  const rowsOf = (view: ReturnType<typeof open>, heading: string) => {
    const result: string[] = [];
    let inside = false;
    for (const item of view.doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr")) {
      if (item.classList.contains("sidebar-group")) { inside = item.textContent === heading; continue; }
      if (inside && item.dataset.name) result.push(item.dataset.name);
    }
    return result;
  };

  it("adds the Style and template and Resources sub-groups under .NET only when the object has styling", () => {
    const none = show({ applicable: false }, []);
    expect(subgroups(none)).not.toContain("Style and template");
    expect(subgroups(none)).not.toContain("Resources");
    const view = show();
    expect(subgroups(view)).toEqual(expect.arrayContaining(["Style and template", "Resources"]));
    expect(subgroups(view).indexOf("Style and template")).toBeLessThan(subgroups(view).indexOf("Resources"));
    expect(view.errors).toEqual([]);
  });

  it("lists the style, its setters, its triggers and its templates", () => {
    const view = show();
    expect(rowsOf(view, "Style and template")).toEqual([
      "Style", "Setter Control.Padding", "Setter Control.Foreground", "Setter Control.Tag", "Triggers[0]", "Triggers[1]", "BasedOn[0]",
      "ControlTemplate", "ItemTemplate", "ItemContainerStyle", "ItemsPanel", "TemplatedParent",
    ]);
    expect(view.value("Style")).toBe("Button (Fancy)");
    expect(view.value("Setter Control.Padding")).toBe("4,4,4,4");
    // Markup is named, never evaluated.
    expect(view.value("Setter Control.Foreground")).toBe("{DynamicResource Accent}");
    expect(view.value("Setter Control.Tag")).toBe("App.Marker");
    expect(view.value("BasedOn[0]")).toBe("Button (Base)");
    expect(view.value("ControlTemplate")).toBe("Button");
    expect(view.value("ItemTemplate")).toBe("DataType Person");
    expect(view.value("ItemsPanel")).toBe("WrapPanel");
    expect(view.value("ItemContainerStyle")).toBe("ListBoxItem");
    expect(view.errors).toEqual([]);
  });

  it("opens a trigger to its conditions, its active state and its setters", () => {
    const view = show();
    expect(view.value("Triggers[0]")).toBe("Trigger IsEnabled = false; inactive");
    expect(view.value("Triggers[1]")).toBe("DataTrigger {Binding Path=Ready} = true; unknown");
    expect(toggle(row(view, "Triggers[0]")).getAttribute("aria-expanded")).toBe("false");
    expect(view.names()).not.toContain("Triggers[0].Condition IsEnabled");
    toggle(row(view, "Triggers[0]")).click();
    expect(toggle(row(view, "Triggers[0]")).getAttribute("aria-expanded")).toBe("true");
    expect(view.value("Triggers[0].Condition IsEnabled")).toBe("= false (inactive)");
    expect(view.value("Triggers[0].Setter UIElement.Opacity")).toBe("0.5");
    toggle(row(view, "Triggers[1]")).click();
    expect(view.value("Triggers[1].Condition {Binding Path=Ready}")).toBe("= true (unknown)");
    toggle(row(view, "Triggers[0]")).click();
    expect(view.names()).not.toContain("Triggers[0].Condition IsEnabled");
    expect(view.errors).toEqual([]);
  });

  it("opens the based-on styles, the template parts and the item container style", () => {
    const view = show();
    toggle(row(view, "BasedOn[0]")).click();
    expect(view.value("BasedOn[0].Setter Control.Margin")).toBe("2");
    toggle(row(view, "ControlTemplate")).click();
    expect(view.value("ControlTemplate.Triggers[0]")).toBe("Trigger PART_Border.Opacity = 1; unknown");
    expect(view.value("ControlTemplate.Part PART_Border")).toBe("System.Windows.Controls.Border");
    toggle(row(view, "ItemContainerStyle")).click();
    expect(view.value("ItemContainerStyle.Setter Control.Padding")).toBe("3");
    // A template with nothing to open has no toggle.
    expect(row(view, "ItemTemplate")!.querySelector("button.property-toggle")).toBeNull();
    expect(view.errors).toEqual([]);
  });

  it("expands objects through the member flow in the styling scope", () => {
    const view = show();
    toggle(row(view, "TemplatedParent")).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "styling:parent", scope: "styling" });
    toggle(row(view, "Setter Control.Tag")).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "styling:tag", scope: "styling" });
    toggle(row(view, "ControlTemplate")).click();
    toggle(row(view, "ControlTemplate.Part PART_Border")).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "styling:border", scope: "styling" });
    // The host answers with the members; they appear under the row.
    const child = { id: "child", member: member("Parent", { memberKey: "clr:Parent" }), value: text("inner") };
    view.send(managed({ sequence: 3, styling, stylingObjects: objects.map((item) => item.id === "row-parent" ? { ...item, children: [child] } : item) }));
    expect(view.value("TemplatedParent.Parent")).toBe("inner");
    expect(view.errors).toEqual([]);
  });

  it("lists the local resources by key, each saying it is read on expanding, then the merged dictionaries", () => {
    const view = show();
    expect(rowsOf(view, "Resources")).toEqual(["Title", "Accent", "System.Windows.Controls.Button", "MergedDictionaries[0]", "MergedDictionaries[1]", "Application resources"]);
    expect(view.value("Title")).toBe("(expand to read)");
    expect(view.value("Accent")).toBe("(expand to read)");
    expect(view.value("System.Windows.Controls.Button")).toBe("(expand to read)");
    expect(view.value("MergedDictionaries[0]")).toBe("Themes/Dark.xaml");
    expect(view.value("MergedDictionaries[1]")).toBe("(inline)");
    expect(toggle(row(view, "Title")).getAttribute("aria-label")).toBe("Read the value of Title");
    toggle(row(view, "Accent")).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "styling:accent", scope: "styling" });
    toggle(row(view, "System.Windows.Controls.Button")).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "styling:button-style", scope: "styling" });
    expect(view.errors).toEqual([]);
  });

  it("shows a resource's value once the host has read it, and offers object resources to expand", () => {
    const view = show();
    const read = (extra: Record<string, unknown>) => objects.map((item) => (item as { id: string }).id === "row-title" ? { ...item, text: undefined, valueType: "System.String", value: text("Hello") } : (item as { id: string }).id === "row-accent" ? { ...item, text: undefined, valueType: "System.Windows.Media.SolidColorBrush", value: handle("accent"), ...extra } : item);
    view.send(managed({ sequence: 3, styling, stylingObjects: read({}) }));
    expect(view.value("Title")).toBe("Hello");
    // A scalar has nothing more to open; an object resource expands through the member flow.
    expect(row(view, "Title")!.querySelector("button.property-toggle")).toBeNull();
    expect(view.value("Accent")).toBe("System.Windows.Media.SolidColorBrush");
    expect(toggle(row(view, "Accent")).getAttribute("aria-label")).toBe("Expand Accent");
    toggle(row(view, "Accent")).click();
    expect(view.posts.filter((post) => (post as { memberKey?: string }).memberKey === "styling:accent")).toHaveLength(1);
    const child = { id: "child", member: member("Color", { memberKey: "clr:Color" }), value: text("Red") };
    view.send(managed({ sequence: 4, styling, stylingObjects: read({ children: [child] }) }));
    expect(view.value("Accent.Color")).toBe("Red");
    expect(view.errors).toEqual([]);
  });

  it("says why a resource has no value, and lets the row be expanded again", () => {
    const view = show();
    view.send(managed({ sequence: 3, styling, stylingObjects: objects.map((item) => (item as { id: string }).id === "row-title" ? { ...item, text: "(not found: the resource is gone)" } : item) }));
    expect(view.value("Title")).toBe("(not found: the resource is gone)");
    expect(toggle(row(view, "Title")).getAttribute("aria-label")).toBe("Read the value of Title");
    expect(view.errors).toEqual([]);
  });

  it("summarizes the application resources in one row that opens to the first page", () => {
    const view = show();
    expect(view.value("Application resources")).toBe("250 resources");
    expect(view.names()).not.toContain("Application.AppTitle");
    toggle(row(view, "Application resources")).click();
    expect(view.value("Application.AppTitle")).toBe("(expand to read)");
    toggle(row(view, "Application.AppTitle")).click();
    expect(view.posts).toContainEqual({ type: "managedExpand", memberKey: "styling:app-title", scope: "styling" });
    expect(view.value("Application.Resources")).toBe("1 of 250 shown");
    toggle(row(view, "Application resources")).click();
    expect(view.names()).not.toContain("Application.AppTitle");
  });

  it("filters the rows with the search box and collapses each sub-group", () => {
    const view = show();
    view.type(view.doc.querySelector<HTMLInputElement>("#sidebar-search")!, "padding");
    expect(rowsOf(view, "Style and template")).toEqual(["Setter Control.Padding"]);
    expect(subgroups(view)).not.toContain("Resources");
    view.type(view.doc.querySelector<HTMLInputElement>("#sidebar-search")!, "");
    const heading = [...view.doc.querySelectorAll<HTMLButtonElement>("tr.sidebar-group button")].find((button) => button.textContent === "Resources")!;
    heading.click();
    expect(rowsOf(view, "Resources")).toEqual([]);
    expect(rowsOf(view, "Style and template").length).toBeGreaterThan(0);
    expect(view.errors).toEqual([]);
  });

  it("starts closed again for another object", () => {
    const view = show();
    toggle(row(view, "Triggers[0]")).click();
    expect(view.names()).toContain("Triggers[0].Condition IsEnabled");
    view.send({ type: "selected", nodeId: "border", properties: { ...presenterProperties, info: borderNode.info } });
    view.send({ type: "selected", nodeId: "presenter", properties: presenterProperties });
    view.send(managed({ sequence: 5, styling, stylingObjects: objects }));
    expect(view.names()).not.toContain("Triggers[0].Condition IsEnabled");
  });
});

describe("Events in the Properties sidebar", () => {
  const handler = (type: string, method: string, handledEventsToo?: boolean) => ({ declaringType: type, method, ...(handledEventsToo === undefined ? {} : { handledEventsToo }) });
  const routed = (name: string, handlers: unknown[] | undefined, extra: Record<string, unknown> = {}) => ({ kind: "routed", name, declaringType: "System.Windows.UIElement", handlerType: "System.Windows.RoutedEventHandler", strategy: name.startsWith("Preview") ? "tunnel" : "bubble", handlersKnown: !!handlers, handlerCount: handlers?.length ?? 0, handlersTruncated: false, handlers: handlers ?? [], ...extra });
  const clr = (name: string, subscribers: unknown[] | undefined, extra: Record<string, unknown> = {}) => ({ kind: "clr", name, declaringType: "Demo.Model", handlerType: "System.EventHandler", isStatic: false, subscribersKnown: !!subscribers, subscriberCount: subscribers?.length ?? 0, subscribersTruncated: false, subscribers: subscribers ?? [], ...extra });
  const events = [
    routed("Click", [handler("Demo.MainWindow", "OnClick", false), handler("Demo.Logger", "OnAny", true)]),
    clr("Idle", [handler("Demo.Bus", "OnIdle")], { isStatic: true }),
    clr("Changed", [handler("Demo.View", "OnChanged"), handler("Demo.View", "OnChanged")]),
    routed("PreviewMouseDown", []),
    clr("Hidden", undefined),
  ];
  const show = (list: unknown[] = events) => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    view.send(managed({ sequence: 2, events: list }));
    return view;
  };
  const row = (view: ReturnType<typeof open>, name: string) => view.doc.querySelector<HTMLElement>(`#sidebar-rows [data-name="${name}"]`);
  const toggle = (element: Element | null) => element!.querySelector<HTMLButtonElement>("button.property-toggle")!;
  const subgroups = (view: ReturnType<typeof open>) => [...view.doc.querySelectorAll("#sidebar-rows tr.sidebar-group")].map((item) => item.textContent);
  const rowsOf = (view: ReturnType<typeof open>, heading: string) => {
    const result: string[] = [];
    let inside = false;
    for (const item of view.doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr")) {
      if (item.classList.contains("sidebar-group")) { inside = item.textContent === heading; continue; }
      if (inside && item.dataset.name) result.push(item.dataset.name);
    }
    return result;
  };

  it("adds the Events sub-group under .NET only when the object has events", () => {
    expect(subgroups(show([]))).not.toContain("Events");
    const view = show();
    expect(subgroups(view)).toContain("Events");
    expect(view.errors).toEqual([]);
  });

  it("lists one row per event in the order the agent sent them, saying what handles it", () => {
    const view = show();
    expect(rowsOf(view, "Events")).toEqual(["Click", "Idle", "Changed", "PreviewMouseDown", "Hidden"]);
    expect(view.value("Click")).toBe("routed (Bubble), 2 handlers");
    expect(view.value("Idle")).toBe("CLR, 1 subscriber");
    expect(view.value("Changed")).toBe("CLR, 2 subscribers");
    expect(view.value("PreviewMouseDown")).toBe("routed (Tunnel), 0 handlers");
    expect(view.value("Hidden")).toBe("handlers unknown");
    expect(view.errors).toEqual([]);
  });

  it("opens an event to the method of each handler, and says which ones take handled events", () => {
    const view = show();
    expect(view.names()).not.toContain("Click.Demo.MainWindow.OnClick");
    expect(toggle(row(view, "Click")).getAttribute("aria-expanded")).toBe("false");
    toggle(row(view, "Click")).click();
    expect(toggle(row(view, "Click")).getAttribute("aria-expanded")).toBe("true");
    expect(rowsOf(view, "Events").slice(0, 3)).toEqual(["Click", "Click.Demo.MainWindow.OnClick", "Click.Demo.Logger.OnAny"]);
    expect(view.value("Click.Demo.MainWindow.OnClick")).toBe("handler");
    expect(view.value("Click.Demo.Logger.OnAny")).toBe("handledEventsToo");
    toggle(row(view, "Idle")).click();
    expect(view.value("Idle.Demo.Bus.OnIdle")).toBe("subscriber");
    toggle(row(view, "Click")).click();
    expect(view.names()).not.toContain("Click.Demo.MainWindow.OnClick");
    expect(view.errors).toEqual([]);
  });

  it("gives an event without handlers, or with handlers it could not read, nothing to open", () => {
    const view = show();
    expect(row(view, "PreviewMouseDown")!.querySelector("button.property-toggle")).toBeNull();
    expect(row(view, "Hidden")!.querySelector("button.property-toggle")).toBeNull();
    expect(row(view, "Click")!.querySelector("button.property-toggle")).not.toBeNull();
    expect(view.errors).toEqual([]);
  });

  it("keeps a handler that is subscribed twice as two rows, and says when the list was capped", () => {
    const view = show([clr("Changed", [handler("Demo.View", "OnChanged"), handler("Demo.View", "OnChanged")]), routed("Click", Array.from({ length: 32 }, (_, index) => handler("Demo.Window", "On" + index, false)), { handlerCount: 40, handlersTruncated: true })]);
    expect(view.value("Click")).toBe("routed (Bubble), 40 handlers (32 shown)");
    toggle(row(view, "Changed")).click();
    expect(rowsOf(view, "Events").slice(0, 3)).toEqual(["Changed", "Changed.Demo.View.OnChanged", "Changed.Demo.View.OnChanged (2)"]);
    toggle(row(view, "Click")).click();
    expect(view.value("Click.handlers")).toBe("8 more not shown");
    expect(view.errors).toEqual([]);
  });

  it("filters the events with the search box and collapses the sub-group", () => {
    const view = show();
    view.type(view.doc.querySelector<HTMLInputElement>("#sidebar-search")!, "unknown");
    expect(rowsOf(view, "Events")).toEqual(["Hidden"]);
    view.type(view.doc.querySelector<HTMLInputElement>("#sidebar-search")!, "changed");
    expect(rowsOf(view, "Events")).toEqual(["Changed"]);
    view.type(view.doc.querySelector<HTMLInputElement>("#sidebar-search")!, "");
    const heading = [...view.doc.querySelectorAll<HTMLButtonElement>("tr.sidebar-group button")].find((button) => button.textContent === "Events")!;
    heading.click();
    expect(rowsOf(view, "Events")).toEqual([]);
    expect(view.errors).toEqual([]);
  });

  it("describes an event in the tooltip of its name", () => {
    const view = show();
    const text = row(view, "Idle")!.querySelector("th")!.title;
    expect(text).toContain("Demo.Model");
    expect(text).toContain("System.EventHandler");
    expect(text).toContain("CLR event");
    expect(view.errors).toEqual([]);
  });
});

describe("Basic view pins", () => {
  const css1 = css.replace(/\s+/g, " ");
  const pinOf = (view: ReturnType<typeof open>, name: string) => view.doc.querySelector<HTMLButtonElement>(`#sidebar-rows tr[data-name="${name}"] .sidebar-pin`);
  const advanced = (basic: string[] = [...DEFAULT_BASIC_PROPERTIES]) => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession(), { ...basicState, basicProperties: basic });
    return view;
  };
  const toggleMode = (view: ReturnType<typeof open>) => (view.doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
  const sent = (view: ReturnType<typeof open>) => view.posts.filter((post) => post.type === "basicProperty" || post.type === "resetBasicProperties");

  it("shows exactly the stored rows that exist for the object, grouped as the full list is", () => {
    const view = open("properties-view");
    view.send(...hostSession(), { ...basicState, basicProperties: ["Standard/Name", "Extended/AutomationId", ".NET/Content", "Win32 Window/Text", "UI Automation/ClassName", "Standard/Missing"] });
    expect(view.headings()).toEqual(["Standard", "Extended", ".NET", "UI Automation"]);
    expect(view.names()).toEqual(["Name", "AutomationId", "Content", "ClassName"]);
    expect(view.value("Content")).toBe("Hello");
    view.send({ ...basicState, basicProperties: [] });
    expect(view.names()).toEqual([]);
    expect(view.visible("#sidebar-empty")).toBe(true);
    expect(view.text("#sidebar-empty")).toContain("Nothing in the Basic view");
    expect(view.errors).toEqual([]);
  });

  it("ignores entries of the stored list that are not keys", () => {
    const view = open("properties-view");
    view.send(...hostSession(), { ...basicState, basicProperties: ["Standard/Name", "bogus", 5, "Elsewhere/Name", "Standard/Name"] });
    expect(view.names()).toEqual(["Name"]);
  });

  it("puts a pin to the left of every name: highlighted for Basic rows, plain for the others, in the Advanced view", () => {
    const view = advanced();
    const height = pinOf(view, "Height")!, margin = pinOf(view, "Margin")!;
    expect(height.getAttribute("aria-pressed")).toBe("true");
    expect(height.classList.contains("codicon-pinned")).toBe(true);
    expect(height.getAttribute("aria-label")).toBe("Remove Height from Basic view");
    expect(margin.getAttribute("aria-pressed")).toBe("false");
    expect(margin.classList.contains("codicon-pin")).toBe(true);
    expect(margin.getAttribute("aria-label")).toBe("Show Margin in Basic view");
    for (const pin of [height, margin]) {
      expect(pin.tagName).toBe("BUTTON");
      expect(pin.type).toBe("button");
      expect(pin.tabIndex).not.toBe(-1);
      // The first thing in the name cell, so before the name (and before the arrow of a row that opens).
      const cell = pin.closest("th")!;
      expect(cell.firstChild).toBe(pin);
      expect(cell.textContent).toBe(pin.closest("tr")!.dataset.name);
    }
    expect(pin1(view, "Content").parentElement?.firstChild).toBe(pin1(view, "Content"));
    // The stylesheet shows a pin that is not pressed only under the pointer or with the focus; a pressed one always.
    const style = (pin: Element) => view.dom.window.getComputedStyle(pin);
    expect(style(height).opacity).toBe("1");
    expect(style(margin).opacity).toBe("0");
    expect(css1).toContain(".sidebar-row .sidebar-pin { opacity: 0; }");
    expect(css1).toContain(".sidebar-row:hover .sidebar-pin, .sidebar-row:focus-within .sidebar-pin, .sidebar-row .sidebar-pin:focus-visible { opacity: 1; }");
    expect(css1).toMatch(/\.sidebar-row \.sidebar-pin\[aria-pressed="true"\] \{ opacity: 1; color: color-mix\(in srgb, var\(--muted\) 65%, var\(--vscode-foreground, var\(--muted\)\) 35%\); \}/);
    // Hidden by opacity, not display: the button stays reachable with the keyboard.
    expect(css1).not.toMatch(/\.sidebar-pin[^{]*\{[^}]*display: none/);
    expect(view.errors).toEqual([]);
  });
  const pin1 = (view: ReturnType<typeof open>, name: string) => pinOf(view, name)!;

  it("shows only highlighted pins in the Basic view, since every row there is in it", () => {
    const view = advanced();
    toggleMode(view);
    const pins = [...view.doc.querySelectorAll<HTMLButtonElement>("#sidebar-rows .sidebar-pin")];
    expect(pins.length).toBeGreaterThan(0);
    for (const pin of pins) {
      expect(pin.getAttribute("aria-pressed")).toBe("true");
      expect(pin.classList.contains("codicon-pinned")).toBe(true);
      expect(pin.closest("tr")!.classList.contains("in-basic")).toBe(true);
    }
    expect(pins.map((pin) => pin.closest("tr")!.dataset.name)).toEqual(view.names());
  });

  it("reserves the pin's room in every row of the Properties tab, so names line up with or without a pin", () => {
    const view = advanced();
    view.send(managed({ sequence: 2, rows: [{ member: member("DataContext", { category: "dependencyProperty" }), value: { status: "ok", kind: "object" }, children: [{ member: member("Zed"), value: { status: "ok", kind: "string", scalar: "child" } }] }] }));
    expect(view.doc.querySelector<HTMLElement>("#sidebar-table")!.dataset.pins).toBe("true");
    expect(css1).toContain('.sidebar-table[data-pins="true"] tbody th[scope="row"] { padding-left: 42px; }');
    expect(css1).toContain('.sidebar-table[data-pins="true"] th .property-toggle { left: 22px; }');
    expect(css1).toMatch(/\.sidebar-table th \.sidebar-pin \{ position: absolute; left: 4px; top: 50%; width: 18px; transform: translateY\(-50%\); \}/);
    // A row that cannot be pinned still has its cell (and so its room) in the same table.
    expect(view.doc.querySelector('[data-name="DataContext.Zed"] th')).not.toBeNull();
    expect(pinOf(view, "DataContext.Zed")).toBeNull();
    expect(pinOf(view, "DataContext")).not.toBeNull();
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.doc.querySelector<HTMLElement>("#sidebar-table")!.dataset.pins).toBe("false");
  });

  it("adds a row to Basic from its pin, tells the host, and keeps it in its group's order in the Basic view", () => {
    const view = advanced();
    pinOf(view, "Content")!.click();
    expect(sent(view)).toEqual([{ type: "basicProperty", key: ".NET/Content", pinned: true }]);
    expect(pinOf(view, "Content")!.getAttribute("aria-pressed")).toBe("true");
    expect(pinOf(view, "Content")!.getAttribute("aria-label")).toBe("Remove Content from Basic view");
    // Pinning is not copying.
    expect(view.posts.some((post) => post.type === "copy")).toBe(false);
    toggleMode(view);
    expect(view.names()).toEqual(["Enabled", "Height", "Name", "Parent", "Visible", "Width", "ClrClassName", "ClrFullClassName", "Content", "WPFControlName", "WPFControlOrdinalNo", "WPFControlText"]);
    // The host keeps the list and sends it back: the same answer, no change.
    view.send({ ...basicState, basicProperties: [...DEFAULT_BASIC_PROPERTIES, ".NET/Content"] });
    expect(view.names()).toContain("Content");
    expect(view.errors).toEqual([]);
  });

  it("removes any row from Basic from its highlighted pin, the built-in ones included", () => {
    const view = advanced();
    pinOf(view, "Enabled")!.click();
    expect(sent(view)).toEqual([{ type: "basicProperty", key: "Standard/Enabled", pinned: false }]);
    expect(pinOf(view, "Enabled")!.getAttribute("aria-pressed")).toBe("false");
    toggleMode(view);
    expect(view.names()).not.toContain("Enabled");
    expect(view.names()).toContain("Height");
    // In the Basic view the row goes as soon as it is unpinned.
    pinOf(view, "Height")!.click();
    expect(view.names()).not.toContain("Height");
    expect(sent(view).at(-1)).toEqual({ type: "basicProperty", key: "Standard/Height", pinned: false });
    expect(view.errors).toEqual([]);
  });

  it("pins rows of every kind that has a stable key, and no row that has none", () => {
    const view = advanced();
    const rows = ["typeMetadata", "clrProperty", "dependencyProperty", "attachedProperty", "staticProperty", "event", "style", "resource"].map((category, index) => ({ member: member(index === 0 ? "Name" : `Member${index}`, { category, memberKey: `key${index}` }), value: { status: "ok", kind: "string", scalar: `value${index}` } }));
    view.send(managed({ sequence: 2, rows, bindings: [{ memberKey: "key2", kind: "Binding", status: "active", path: "Title" }] }));
    // Standard, Extended, .NET members and UI Automation properties have keys.
    for (const [name, key] of [["Height", "Standard/Height"], ["AutomationId", "Extended/AutomationId"], ["Member1", ".NET/Member1"], ["Member3", ".NET/Member3"], ["ClassName", "UI Automation/ClassName"]] as const) {
      expect(pinOf(view, name)?.dataset.key, name).toBe(key);
      expect(view.doc.querySelector(`#sidebar-rows tr[data-name="${name}"]`)?.getAttribute("data-key")).toBe(key);
    }
    // Binding, style, resource and event rows are derived from structures that have no member key: no pin.
    for (const group of ["Bindings", "Style and template", "Resources", "Events"]) {
      const inGroup = [...view.doc.querySelectorAll(`#sidebar-rows tr.sidebar-row[data-key^="${group}/"]`)];
      expect(inGroup.length, group).toBeGreaterThan(0);
      for (const row of inGroup) expect(row.querySelector(".sidebar-pin"), `${group}/${(row as HTMLElement).dataset.name}`).toBeNull();
    }
    // The keys are unique, so a pin always means one row.
    const keys = [...view.doc.querySelectorAll<HTMLElement>("#sidebar-rows .sidebar-pin")].map((pin) => pin.dataset.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const key of keys) expect(key).toMatch(/^(Standard|Extended|\.NET|Win32 Window|UI Automation)\//);
  });

  it("offers a pin for a Win32 Window row with its own group in the key", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession(), { ...basicState }, { type: "selected", nodeId: "presenter", properties: { ...presenterProperties, window: { className: "Edit", text: "hello", handle: 199242, rawStyle: 1, rawExStyle: 0, styles: [], exStyles: [] } } });
    expect(pinOf(view, "Window Class")?.dataset.key).toBe("Win32 Window/Window Class");
    expect(pinOf(view, "Window Class")?.getAttribute("aria-pressed")).toBe("true");
    expect(pinOf(view, "Raw Style")?.dataset.key).toBe("Win32 Window/Raw Style");
    expect(pinOf(view, "Raw Style")?.getAttribute("aria-pressed")).toBe("false");
  });

  it("has no pins on the Fields and Methods tabs", () => {
    const view = advanced();
    for (const tab of ["fields", "methods"]) {
      (view.doc.querySelector(`[data-sidebar-tab="${tab}"]`) as HTMLButtonElement).click();
      expect(view.doc.querySelectorAll("#sidebar-rows .sidebar-pin")).toHaveLength(0);
    }
  });

  it("restores the default list with Reset Basic view, which is only offered on the Properties tab and enabled when the list differs", () => {
    const view = advanced();
    const reset = view.doc.querySelector<HTMLButtonElement>("#sidebar-reset-basic")!;
    expect(reset.textContent?.trim()).toBe("Reset Basic view");
    expect(view.visible("#sidebar-reset-basic")).toBe(true);
    expect(reset.disabled).toBe(true);
    pinOf(view, "Margin")!.click();
    pinOf(view, "Enabled")!.click();
    expect(reset.disabled).toBe(false);
    reset.click();
    expect(sent(view).at(-1)).toEqual({ type: "resetBasicProperties" });
    expect(pinOf(view, "Margin")!.getAttribute("aria-pressed")).toBe("false");
    expect(pinOf(view, "Enabled")!.getAttribute("aria-pressed")).toBe("true");
    expect(reset.disabled).toBe(true);
    toggleMode(view);
    expect(view.names().slice(0, 6)).toEqual(["Enabled", "Height", "Name", "Parent", "Visible", "Width"]);
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.visible("#sidebar-reset-basic")).toBe(false);
    expect(view.errors).toEqual([]);
  });

  it("follows the setting when it changes elsewhere, and its default when that changes", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    expect(view.names()).toContain("Enabled");
    view.send({ ...basicState, basicProperties: ["Standard/Width"] });
    expect(view.names()).toEqual(["Width"]);
    expect(view.doc.querySelector<HTMLButtonElement>("#sidebar-reset-basic")!.disabled).toBe(false);
    view.send({ ...basicState, basicProperties: ["Standard/Width"], basicDefaults: ["Standard/Width"] });
    expect(view.doc.querySelector<HTMLButtonElement>("#sidebar-reset-basic")!.disabled).toBe(true);
  });

  it("keeps the focus on the pin that was pressed", () => {
    const view = advanced();
    view.doc.body.focus();
    pinOf(view, "Margin")!.click();
    expect(view.doc.activeElement).toBe(pinOf(view, "Margin"));
  });

  it("no longer carries the old pinned list, its message or its setting", () => {
    expect(script).not.toContain("pinProperty");
    expect(script).not.toContain("shownProperties");
    expect(html).not.toContain("pinned-group");
    expect(css).not.toContain(".property-pin");
    const view = open("properties-view");
    view.send(...hostSession(), { ...basicState, shownProperties: ["HelpText"] });
    expect(view.posts.some((post) => post.type === "pinProperty")).toBe(false);
  });
});

describe("Copy label", () => {
  const view = () => {
    const page = open("properties-view", { sidebarShowAll: true });
    page.send(...hostSession());
    return page;
  };
  const click = (page: ReturnType<typeof open>, cell: Element, x: number, y: number) =>
    cell.dispatchEvent(new page.dom.window.MouseEvent("click", { bubbles: true, clientX: x, clientY: y }));
  const toast = (page: ReturnType<typeof open>) => page.doc.querySelector<HTMLElement>("#copy-toast")!;

  it("says Name copied beside the pointer for the name cell and Value copied for the value cell, and fades after about a second", async () => {
    const page = view();
    const row = page.doc.querySelector<HTMLTableRowElement>('[data-name="Height"]')!;
    expect(toast(page).hidden).toBe(true);
    click(page, row.cells[0]!, 120, 80);
    expect(toast(page).hidden).toBe(false);
    expect(toast(page).textContent).toBe("Name copied");
    expect(toast(page).style.left).toBe("132px");
    expect(toast(page).style.top).toBe("94px");
    expect(page.text("#copy-announcer")).toBe("Name copied");
    click(page, row.cells[1]!, 200, 90);
    expect(toast(page).textContent).toBe("Value copied");
    expect(toast(page).style.left).toBe("212px");
    // The old header feedback is gone.
    expect(page.doc.querySelector("#sidebar-copy-feedback")).toBeNull();
    expect(row.cells[1]!.classList.contains("copied")).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 780));
    expect(toast(page).classList.contains("fading")).toBe(true);
    expect(toast(page).hidden).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(toast(page).hidden).toBe(true);
    expect(page.text("#copy-announcer")).toBe("");
    expect(row.cells[1]!.classList.contains("copied")).toBe(false);
    expect(page.errors).toEqual([]);
  });

  it("keeps the label inside the window", () => {
    const page = view();
    const row = page.doc.querySelector<HTMLTableRowElement>('[data-name="Height"]')!;
    click(page, row.cells[0]!, 5000, 5000);
    expect(parseFloat(toast(page).style.left)).toBeLessThanOrEqual(page.dom.window.innerWidth - 4);
    expect(parseFloat(toast(page).style.top)).toBeLessThanOrEqual(page.dom.window.innerHeight - 4);
    click(page, row.cells[0]!, -50, -50);
    expect(toast(page).style.left).toBe("4px");
    expect(toast(page).style.top).toBe("4px");
    Object.defineProperty(toast(page), "offsetWidth", { configurable: true, value: 90 });
    Object.defineProperty(toast(page), "offsetHeight", { configurable: true, value: 20 });
    click(page, row.cells[0]!, page.dom.window.innerWidth - 10, page.dom.window.innerHeight - 5);
    expect(parseFloat(toast(page).style.left) + 90).toBeLessThanOrEqual(page.dom.window.innerWidth - 4);
    expect(parseFloat(toast(page).style.top) + 20).toBeLessThanOrEqual(page.dom.window.innerHeight - 4);
  });

  it("places the label at the cell for a copy from the keyboard, and announces it", () => {
    const page = view();
    const row = page.doc.querySelector<HTMLTableRowElement>('[data-name="Height"]')!;
    row.cells[1]!.getBoundingClientRect = () => ({ left: 100, top: 200, right: 160, bottom: 220, width: 60, height: 20, x: 100, y: 200, toJSON() {} });
    key(page, row, { key: "Enter" });
    expect(toast(page).textContent).toBe("Value copied");
    expect(toast(page).style.left).toBe("112px");
    expect(toast(page).style.top).toBe("214px");
    expect(page.text("#copy-announcer")).toBe("Value copied");
    key(page, row, { key: "c", ctrlKey: true });
    expect(toast(page).textContent).toBe("Value copied");
  });

  it("announces politely, stays out of the accessibility tree itself and takes no pointer events", () => {
    const page = view();
    const announcer = page.doc.querySelector("#copy-announcer")!;
    expect(announcer.getAttribute("role")).toBe("status");
    expect(announcer.getAttribute("aria-live")).toBe("polite");
    expect(toast(page).getAttribute("aria-hidden")).toBe("true");
    const css1 = css.replace(/\s+/g, " ");
    expect(css1).toContain("pointer-events: none");
  });

  it("copies nothing and shows nothing for a value that cannot be copied", () => {
    const page = view();
    const row = page.doc.querySelector<HTMLTableRowElement>('[data-name="Content"]')!;
    page.send(managed({ sequence: 2, rows: [{ member: member("Content"), value: { status: "exception", kind: "unavailable", message: "System.InvalidOperationException" } }] }));
    const failed = page.doc.querySelector<HTMLTableRowElement>('[data-name="Content"]')!;
    expect(row.isConnected).toBe(false);
    failed.cells[1]!.click();
    expect(failed.cells[1]!.classList.contains("copied")).toBe(false);
  });

  it("is green-tinted from theme colours, readable in light, dark, high-contrast and forced-colour themes", () => {
    const css1 = css.replace(/\s+/g, " ");
    const rule = css1.slice(css1.indexOf(".copy-toast {"), css1.indexOf("}", css1.indexOf(".copy-toast {")) + 1);
    expect(rule).toContain("--vscode-testing-iconPassed");
    expect(rule).toContain("--vscode-charts-green");
    expect(rule).toMatch(/background: color-mix\(in srgb, var\(--vscode-testing-iconPassed[^;]*var\(--vscode-editorHoverWidget-background/);
    expect(rule).toContain("color: var(--vscode-editorHoverWidget-foreground");
    expect(rule).toContain("position: fixed");
    expect(css1).toContain("body.vscode-high-contrast .copy-toast");
    expect(css1).toMatch(/@media \(forced-colors: active\) \{ \.copy-toast \{[^}]*border-color: CanvasText/);
    expect(css1).toMatch(/@media \(prefers-reduced-motion: reduce\) \{ \.copy-toast \{ transition: none; \} \}/);
  });
});

describe("Description section", () => {
  it("is gone from the page, the stylesheet and the script", () => {
    expect(html).not.toContain("sidebar-description");
    expect(html).not.toContain("Select a row to see its description");
    expect(css).not.toContain("sidebar-description");
    expect(css).not.toContain(".described");
    expect(script).not.toContain("describeSidebar");
    expect(script).not.toContain("describedKey");
    expect(script).not.toContain("sidebar-description");
  });

  it("keeps descriptions as native tooltips on the name cell, which also carry the full name", () => {
    const page = open("properties-view", { sidebarShowAll: true });
    page.send(...hostSession());
    for (const row of page.doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr.sidebar-row")) {
      const title = (row.cells[0] as HTMLElement).title;
      expect(title.split("\n")[0], row.dataset.name).toBe(row.dataset.name);
      // One compact line or a few short lines.
      expect(title.split("\n").length).toBeLessThanOrEqual(9);
      for (const line of title.split("\n")) expect(line.length).toBeLessThanOrEqual(175);
    }
    expect(tooltip(page, "Enabled")).toContain("Whether the control accepts input");
    expect(tooltip(page, "Visible")).toContain("Whether the object is shown");
  });

  it("shortens a long description line", () => {
    const page = open("properties-view", { sidebarShowAll: true });
    page.send(...hostSession(), managed({ sequence: 2, rows: [{ member: member("Content", { declaredType: "T".repeat(400) }), value: { status: "ok", kind: "string", scalar: "x", runtimeType: "System.String" } }] }));
    const lines = tooltip(page, "Content").split("\n");
    expect(lines.some((line) => line.endsWith("…"))).toBe(true);
    expect(Math.max(...lines.map((line) => line.length))).toBeLessThanOrEqual(175);
  });
});

describe("Splitter", () => {
  const workspace = (page: ReturnType<typeof open>) => page.doc.querySelector<HTMLElement>("#workspace")!;
  const treeWidthPosts = (page: ReturnType<typeof open>) => page.posts.filter((post) => post.type === "treeWidth");
  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  const withWidth = (page: ReturnType<typeof open>, width: number) => {
    workspace(page).getBoundingClientRect = () => ({ left: 0, top: 0, right: width, bottom: 600, width, height: 600, x: 0, y: 0, toJSON() {} });
  };
  const drag = (page: ReturnType<typeof open>, ...positions: number[]) => {
    const splitter = page.doc.querySelector<HTMLElement>("#splitter")!;
    (splitter as unknown as { setPointerCapture: (id: number) => void }).setPointerCapture = () => {};
    const down = new page.dom.window.MouseEvent("pointerdown", { bubbles: true, cancelable: true });
    Object.assign(down, { pointerId: 1 });
    splitter.dispatchEvent(down);
    for (const x of positions) splitter.dispatchEvent(new page.dom.window.MouseEvent("pointermove", { bubbles: true, clientX: x }));
    return () => splitter.dispatchEvent(new page.dom.window.Event("lostpointercapture"));
  };
  const state = (page: ReturnType<typeof open>, extra: Record<string, unknown> = {}) => page.send({ type: "state", appRunning: true, hasProject: true, ...extra });

  it("starts with the default split: the tree takes everything except what the selected object's pane needs", () => {
    const page = open("spy-view");
    page.send(...hostSession());
    expect(workspace(page).dataset.split).toBeUndefined();
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("");
    expect(workspace(page).style.getPropertyValue("--details-min")).toBe("260px");
    const css1 = css.replace(/\s+/g, " ");
    expect(css1).toContain("#workspace { display: grid; grid-template-columns: minmax(200px, 1fr) 5px var(--details-min, 260px);");
    expect(css1).toContain('#workspace[data-split="custom"] { grid-template-columns: minmax(200px, var(--tree-width)) 5px minmax(var(--details-min, 260px), 1fr); }');
    expect(css1).not.toContain("36%");
    expect(page.errors).toEqual([]);
  });

  it("measures the selected object's pane: 260px, or what its header and locator button need when more", () => {
    const page = open("spy-view");
    page.send(...hostSession());
    const wide = (id: string, width: number) => Object.defineProperty(page.doc.getElementById(id)!, "offsetWidth", { configurable: true, value: width });
    wide("details-title", 90); wide("highlight", 100); wide("locator-panel", 330); wide("generate", 300);
    page.dom.window.dispatchEvent(new page.dom.window.Event("resize"));
    const measured = parseFloat(workspace(page).style.getPropertyValue("--details-min"));
    // The panel's padding and border are added to the button; the header's to its two parts.
    expect(measured).toBeGreaterThanOrEqual(300 + 24);
    expect(measured).toBeLessThanOrEqual(300 + 24 + 8);
    wide("generate", 150); wide("locator-panel", 180);
    page.dom.window.dispatchEvent(new page.dom.window.Event("resize"));
    expect(workspace(page).style.getPropertyValue("--details-min")).toBe("260px");
  });

  it("restores the width the host kept, clamped to the window, without telling the host back", async () => {
    const page = open("spy-view");
    withWidth(page, 1000);
    state(page, { treeWidth: 420 });
    expect(workspace(page).dataset.split).toBe("custom");
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("420px");
    state(page, { treeWidth: 900 });
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("715px"); // 1000 - 25 - 260
    state(page, { treeWidth: 50 });
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("200px");
    await wait(350);
    expect(treeWidthPosts(page)).toEqual([]);
    expect(page.errors).toEqual([]);
  });

  it("keeps the chosen width when the window shrinks and grows again", () => {
    const page = open("spy-view");
    withWidth(page, 1400);
    state(page, { treeWidth: 900 });
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("900px");
    withWidth(page, 800);
    page.dom.window.dispatchEvent(new page.dom.window.Event("resize"));
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("515px");
    withWidth(page, 1400);
    page.dom.window.dispatchEvent(new page.dom.window.Event("resize"));
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("900px");
  });

  it("shows a width restored before the window had a size, once it has one", () => {
    const page = open("spy-view");
    state(page, { treeWidth: 650 });
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("650px");
    withWidth(page, 700);
    page.dom.window.dispatchEvent(new page.dom.window.Event("resize"));
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("415px");
  });

  it("keeps a dragged width: one message after the drag settles, with the clamped width", async () => {
    const page = open("spy-view");
    withWidth(page, 1000);
    const release = drag(page, 300, 350, 400);
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("400px");
    expect(workspace(page).dataset.split).toBe("custom");
    expect(treeWidthPosts(page)).toEqual([]);
    // A state that arrives mid-drag does not pull the splitter back.
    state(page, { treeWidth: 250 });
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("400px");
    release();
    await wait(350);
    expect(treeWidthPosts(page)).toEqual([{ type: "treeWidth", width: 400 }]);
    // Dragged past the limit, the width kept is the one on screen.
    drag(page, 5000)();
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("715px");
    await wait(350);
    expect(treeWidthPosts(page).at(-1)).toEqual({ type: "treeWidth", width: 715 });
    expect(page.errors).toEqual([]);
  });

  it("keeps a width set with the keyboard too", async () => {
    const page = open("spy-view");
    withWidth(page, 1000);
    Object.defineProperty(page.doc.getElementById("tree-pane")!, "offsetWidth", { configurable: true, value: 500 });
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("520px");
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("480px");
    await wait(350);
    expect(treeWidthPosts(page)).toEqual([{ type: "treeWidth", width: 480 }]);
  });

  it("returns to the default and forgets the stored width on a double-click", async () => {
    const page = open("spy-view");
    withWidth(page, 1000);
    state(page, { treeWidth: 420 });
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.MouseEvent("dblclick", { bubbles: true }));
    expect(workspace(page).dataset.split).toBeUndefined();
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("");
    expect(treeWidthPosts(page)).toEqual([{ type: "treeWidth", width: null }]);
    // Nothing is left to say a moment later, and a width dragged just before is not sent after the reset.
    drag(page, 333)();
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.MouseEvent("dblclick", { bubbles: true }));
    await wait(350);
    expect(treeWidthPosts(page)).toEqual([{ type: "treeWidth", width: null }, { type: "treeWidth", width: null }]);
    // With nothing to forget, a double-click says nothing.
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.MouseEvent("dblclick", { bubbles: true }));
    expect(treeWidthPosts(page)).toHaveLength(2);
  });

  it("resets from the keyboard with Home", () => {
    const page = open("spy-view");
    withWidth(page, 1000);
    state(page, { treeWidth: 420 });
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    expect(workspace(page).dataset.split).toBeUndefined();
    expect(treeWidthPosts(page)).toEqual([{ type: "treeWidth", width: null }]);
  });

  it("leaves the stacked layout alone: it resizes the tree's height and keeps nothing", async () => {
    const page = open("spy-view", {}, { narrow: true });
    workspace(page).getBoundingClientRect = () => ({ left: 0, top: 0, right: 400, bottom: 800, width: 400, height: 800, x: 0, y: 0, toJSON() {} });
    state(page, { treeWidth: 420 });
    expect(workspace(page).style.getPropertyValue("--tree-width")).toBe("");
    expect(workspace(page).dataset.split).toBeUndefined();
    drag(page, 0)();
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.MouseEvent("pointermove", { bubbles: true, clientY: 300 }));
    page.doc.getElementById("splitter")!.dispatchEvent(new page.dom.window.MouseEvent("dblclick", { bubbles: true }));
    expect(workspace(page).style.getPropertyValue("--tree-height")).toBe("");
    await wait(350);
    expect(treeWidthPosts(page)).toEqual([]);
    expect(css.replace(/\s+/g, " ")).toContain('@media (max-width: 620px) { #workspace, #workspace[data-split="custom"] { grid-template-columns: minmax(0, 1fr);');
  });
});

describe("review fixes for the Spy and Properties webviews", () => {
  const types = (posts: Message[]) => posts.map((post) => post.type as string);
  const tree = () => {
    const child = { nodeId: "border", hasChildren: true, info: { controlType: "Pane", name: "Border", className: "Border" } };
    const leaf = { nodeId: "leaf", hasChildren: false, info: { controlType: "Button", name: "Save" } };
    return { child, leaf };
  };
  const refresh = (view: ReturnType<typeof open>) => {
    const { child, leaf } = tree();
    view.send({ type: "state", hasProject: true }, { type: "roots", nodes: [windowNode] }, { type: "children", nodeId: "win", nodes: [child], expanded: true }, { type: "children", nodeId: "border", nodes: [leaf], expanded: true });
    view.posts.length = 0;
    view.send({ type: "rootsDiff", nodes: [windowNode], revision: 1, refresh: true });
    view.send({ type: "childrenDiff", nodeId: "win", nodes: [child], revision: 1 });
    view.send({ type: "childrenDiff", nodeId: "border", nodes: [leaf], revision: 1 });
  };

  it("refreshes each open node once in the Spy panel and never from the Properties sidebar", () => {
    const panel = open("spy-view");
    refresh(panel);
    const asked = panel.posts.filter((post) => post.type === "refreshChildren").map((post) => post.nodeId);
    expect(asked).toEqual(["win", "border"]);
    expect(types(panel.posts)).toContain("refreshCounts");
    const sidebar = open("properties-view");
    refresh(sidebar);
    expect(sidebar.posts).toEqual([]);
    expect(sidebar.errors.concat(panel.errors)).toEqual([]);
  });

  it("does not let the sidebar's stale copy clear the selection or overwrite the remembered expansion", () => {
    const sidebar = open("properties-view");
    const { child, leaf } = tree();
    sidebar.send({ type: "roots", nodes: [windowNode] }, { type: "children", nodeId: "win", nodes: [child], expanded: true }, { type: "children", nodeId: "border", nodes: [leaf], expanded: true }, { type: "selected", nodeId: "leaf", properties: { source: "wpf", info: leaf.info, properties: {} } });
    sidebar.posts.length = 0;
    sidebar.send({ type: "rootsDiff", nodes: [windowNode], revision: 1 }, { type: "childrenDiff", nodeId: "win", nodes: [], revision: 1 });
    expect(types(sidebar.posts).filter((type) => ["selectionRemoved", "expandedPaths", "refreshChildren", "expand", "treeMore", "treeAttach", "select"].includes(type))).toEqual([]);
  });

  it("does not offer Try again for the permanent window reason, and still does for others", () => {
    const view = open("spy-view");
    view.send({ type: "selected", nodeId: "win", properties: { source: "wpf", info: windowNode.info, properties: {} } });
    view.send({ type: "suggestionUnavailable", nodeId: "win", reason: "Select a window descendant to generate an element locator" });
    expect(view.doc.querySelector<HTMLElement>("#generate")!.hidden).toBe(true);
    expect(view.text("#code")).toContain("Select a window descendant");
    view.send({ type: "suggestionUnavailable", nodeId: "win", reason: "Timed out" });
    expect(view.doc.querySelector<HTMLElement>("#generate")!.hidden).toBe(false);
    expect(view.text("#generate-label")).toBe("Try again");
  });

  it("says which application is not running when no roots are listed", () => {
    const view = open("spy-view");
    view.send({ type: "state", hasProject: true, appRunning: false, targetName: "Contoso", appName: "Contoso.exe" }, { type: "roots", nodes: [] });
    expect(view.text("#tree-empty-description")).toBe("Contoso.exe is not running. Launch it from the WinTestKit view, or use Show Other Apps.");
  });

  it("marks the actions menu items as menu items, moves between them with the arrow keys and styles them as menu entries", () => {
    const view = open("properties-view");
    const items = [...view.doc.querySelectorAll<HTMLButtonElement>(".sidebar-actions-menu button")];
    expect(items.map((item) => item.getAttribute("role"))).toEqual(["menuitem", "menuitem", "menuitem", "menuitem", "menuitem"]);
    const actions = view.doc.querySelector<HTMLDetailsElement>("#sidebar-actions")!;
    for (let node: HTMLElement | null = actions; node; node = node.parentElement) node.hidden = false;
    const button = actions.querySelector<HTMLElement>("summary")!;
    button.click();
    expect(actions.open).toBe(true);
    expect(view.doc.activeElement).toBe(items[0]);
    const press = (key: string) => items[0]!.dispatchEvent(new view.dom.window.KeyboardEvent("keydown", { key, bubbles: true }));
    expect(view.doc.activeElement?.id).toBe("sidebar-detach");
    press("ArrowDown");
    expect(view.doc.activeElement).toBe(items[1]);
    press("ArrowUp"); press("ArrowUp");
    expect(view.doc.activeElement).toBe(items[2]);
    items[2]!.dispatchEvent(new view.dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(actions.open).toBe(false);
    expect(view.doc.activeElement).toBe(button);
    expect(css).toMatch(/\.sidebar-actions-menu button \{[^}]*background: transparent/);
    expect(css).toMatch(/\.sidebar-actions-menu button:hover[^{]*\{[^}]*menu-selectionBackground/);
  });

  it("wraps the suggested locator and shows the full text as a tooltip", () => {
    const view = open("spy-view");
    view.send({ type: "selected", nodeId: "win", properties: { source: "wpf", info: windowNode.info, properties: {} } }, { type: "suggestion", nodeId: "win", suggestion: { attributeName: "save", code: 'by.name("a very long locator name")', strategy: "name", unique: true, matchCount: 1, helpers: [] } });
    expect(view.doc.querySelector<HTMLElement>("#locator-result")!.title).toBe('save = by.name("a very long locator name")');
    expect(css).toMatch(/#locator-result \{[^}]*white-space: pre-wrap[^}]*overflow-wrap: anywhere/);
  });

  it("searches every row while the search box has text and returns to the Basic rows when it is cleared", () => {
    const view = open("properties-view");
    view.send(basicState, ...hostSession());
    const search = view.doc.querySelector<HTMLInputElement>("#sidebar-search")!;
    const basicRows = view.names();
    view.type(search, "ClassName");
    const searched = view.names();
    expect(searched.length).toBeGreaterThan(0);
    for (const row of searched) expect(row?.toLowerCase() + " ").toBeDefined();
    view.type(search, "");
    expect(view.names()).toEqual(basicRows);
    expect(view.doc.querySelector<HTMLInputElement>("#sidebar-mode")!.checked).toBe(false);
  });

  it("clears the copied highlight of the first cell when a second cell is copied", () => {
    const view = open("properties-view", { sidebarShowAll: true });
    view.send(...hostSession());
    const row = view.doc.querySelector<HTMLTableRowElement>('[data-name="Height"]')!;
    const click = (cell: Element) => cell.dispatchEvent(new view.dom.window.MouseEvent("click", { bubbles: true }));
    click(row.cells[0]!);
    click(row.cells[1]!);
    expect(row.cells[0]!.classList.contains("copied")).toBe(false);
    expect(row.cells[1]!.classList.contains("copied")).toBe(true);
  });
});
