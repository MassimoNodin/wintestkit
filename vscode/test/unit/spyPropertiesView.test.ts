import { readFileSync } from "node:fs";
import { JSDOM, VirtualConsole } from "jsdom";
import { describe, expect, it } from "vitest";

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

function open(surface: Surface, state: Record<string, unknown> = {}) {
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
    matchMedia: () => ({ matches: false, addEventListener() {} }),
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

const windowNode = { nodeId: "win", source: "wpf", hasChildren: true, info: { controlType: "Window", name: "Fixture", className: "FixtureWindow", processId: 42 } };
const borderNode = { nodeId: "border", source: "wpf", hasChildren: true, info: { controlType: "Pane", name: "", className: "Border" }, identity: { type: "System.Windows.Controls.Border" } };
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
// The messages the host replays or sends, in the order it sends them for a selected object.
const hostSession = (): Message[] => [
  { type: "tour", dim: false, spyLit: false },
  { type: "state", picking: false, appRunning: true, targetName: "demo", appName: "Fixture", appPids: [42], hasProject: true, showOtherApps: true, bringToFront: false, shownProperties: [], showRefreshCounts: false },
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

  it("shows tabs, search, the mode switch, the rows and the description once a WPF object is selected", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    for (const selector of ["#sidebar-tab-properties", "#sidebar-tab-fields", "#sidebar-tab-methods", "#sidebar-search", "#sidebar-mode", "#sidebar-rows tr[data-name]", "#sidebar-description", "#sidebar-description-content", "#object-preview"]) {
      expect(view.hiddenReason(selector), selector).toBeUndefined();
    }
    expect(view.visible("#properties-empty")).toBe(false);
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
    expect(view.text("#selection-name")).toBe("Pane");
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
    const view = open("properties-view", { sidebarAdvanced: true });
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
    expect(filtered).toContain("MappedName");
    view.type(view.doc.querySelector("#sidebar-search") as HTMLInputElement, "no-such-row");
    expect(view.names()).toEqual([]);
    expect(view.visible("#sidebar-empty")).toBe(true);
    expect(view.errors).toEqual([]);
  });

  it("3.3 shows exactly the nine Basic rows and remembers the choice", () => {
    const basic = ["Enabled", "Height", "MappedName", "Name", "Parent", "Visible", "Width", "ClrFullClassName", "WPFControlText"];
    const view = open("properties-view");
    view.send(...hostSession());
    expect(view.names()).toEqual(basic);
    expect(view.headings()).toEqual([]);
    expect(view.text("#sidebar-mode")).toBe("Basic");
    (view.doc.querySelector("#sidebar-mode") as HTMLButtonElement).click();
    expect(view.text("#sidebar-mode")).toBe("Advanced");
    expect(view.state()).toMatchObject({ sidebarAdvanced: true });
    // A reopened view starts in the remembered mode.
    const reopened = open("properties-view", view.state());
    reopened.send(...hostSession());
    expect(reopened.text("#sidebar-mode")).toBe("Advanced");
    expect(reopened.headings()[0]).toBe("Standard");
    (reopened.doc.querySelector("#sidebar-mode") as HTMLButtonElement).click();
    expect(open("properties-view", reopened.state()).text("#sidebar-mode")).toBe("Basic");
    expect(view.errors.concat(reopened.errors)).toEqual([]);
  });

  it("3.4 groups Advanced as Standard, Extended, .NET and UI Automation, with every value once", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    expect(view.headings()).toEqual(["Standard", "Extended", ".NET", "UI Automation"]);
    const names = view.names();
    expect(new Set(names).size).toBe(names.length);
    // Name is x:Name, Enabled is IsEnabled, the rectangle rows are Bounds, and the type is shown once.
    for (const duplicate of ["x:Name", "IsEnabled", "Bounds", "Type", "Managed type", "CLR Name", "CLR IsEnabled"]) expect(names, duplicate).not.toContain(duplicate);
    expect(view.value("Name")).toBe("contentSite");
    expect(names.filter((name) => name === "ClrFullClassName")).toHaveLength(1);
    expect(view.doc.body.textContent?.match(/System\.Windows\.Controls\.ContentPresenter/g)?.length).toBeGreaterThan(0);
    const classCells = [...view.doc.querySelectorAll<HTMLTableCellElement>("#sidebar-rows td")].filter((cell) => cell.textContent === "System.Windows.Controls.ContentPresenter");
    expect(classCells).toHaveLength(1);
    // Basic mode has neither groups nor UI Automation.
    (view.doc.querySelector("#sidebar-mode") as HTMLButtonElement).click();
    expect(view.headings()).toEqual([]);
    expect(view.doc.querySelector("#sidebar-rows")?.textContent).not.toContain("UI Automation");
    expect(view.errors).toEqual([]);
  });

  it("3.4 reports FullName as the locator path from the window, MappedName as the defining element and Parent as a link", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    expect(view.value("MappedName")).toBe("Page.contentSite");
    (view.doc.querySelector("#sidebar-mode") as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "generateLocator", nodeId: "presenter" });
    // No unique locator yet: the path is built from the tree, window first.
    expect(view.value("FullName")).toBe('Window("FixtureWindow").WPFObject("Border").WPFObject("contentSite")');
    expect(view.value("Parent")).toBe('WPFObject("Border")');
    // A unique locator from the host replaces the tree path.
    view.send({ type: "suggestion", nodeId: "presenter", suggestion: { unique: true, strategy: "automationId", helpers: [], window: { code: "Window(title='Fixture')" }, code: "WPFObject('contentSite')" } });
    expect(view.value("FullName")).toBe("Window(title='Fixture')\nWPFObject('contentSite')");
    (view.doc.querySelector('[data-name="Parent"] button') as HTMLButtonElement).click();
    expect(view.posts).toContainEqual(expect.objectContaining({ type: "select", nodeId: "border" }));
    expect(view.errors).toEqual([]);
  });

  it("3.4 still has Parent and FullName when the sidebar's tree never saw the object", () => {
    const view = open("properties-view");
    // The host sent no tree, only the selection and the ancestors it read with it.
    view.send({ type: "selected", nodeId: "presenter", properties: presenterProperties });
    expect(view.value("Parent")).toBe('WPFObject("Border")');
    (view.doc.querySelector("#sidebar-mode") as HTMLButtonElement).click();
    expect(view.value("FullName")).toBe('Window("FixtureWindow").WPFObject("Border").WPFObject("contentSite")');
    (view.doc.querySelector('[data-name="Parent"] button') as HTMLButtonElement).click();
    expect(view.posts).toContainEqual({ type: "select", nodeId: "border" });
    expect(view.errors).toEqual([]);
  });

  it("3.6 lists rows as name and value with a menu of row actions and a description pane", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    expect([...view.doc.querySelectorAll(".sidebar-table thead th")].map((cell) => cell.textContent)).toEqual(["Name", "Value", ""]);
    const row = view.doc.querySelector('[data-name="Content"]') as HTMLTableRowElement;
    expect([...row.children].map((cell) => cell.tagName)).toEqual(["TH", "TD", "TD"]);
    const menu = view.doc.querySelector("#sidebar-row-menu") as HTMLElement;
    const labels = () => [...menu.querySelectorAll("button")].map((button) => button.textContent);
    const contextmenu = (target: Element) => {
      const event = new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event;
    };
    // Right-click opens the row's own menu, never the browser's: every item is present, those that do not apply are disabled.
    expect(menu.hidden).toBe(true);
    expect(contextmenu(row).defaultPrevented).toBe(true);
    expect(menu.hidden).toBe(false);
    expect(labels()).toEqual(["Copy value", "Copy name", "Copy locator key", "Expand", "Read again", "Show in Basic view"]);
    const enabled = () => [...menu.querySelectorAll("button")].filter((button) => !button.disabled).map((button) => button.textContent);
    expect(enabled()).toEqual(["Copy value", "Copy name", "Copy locator key", "Read again", "Show in Basic view"]);
    expect(view.text("#sidebar-description-content")).toContain("Runtime type: System.String");
    expect(view.text("#sidebar-description-content")).toContain("Declaring type: System.Windows.Controls.ContentPresenter");
    const choose = (label: string) => {
      if (menu.hidden) contextmenu(row);
      ([...menu.querySelectorAll("button")].find((button) => button.textContent === label) as HTMLButtonElement).click();
    };
    for (const label of ["Copy value", "Copy name", "Copy locator key", "Read again"]) choose(label);
    expect(menu.hidden).toBe(true);
    expect(view.posts).toEqual(expect.arrayContaining([
      { type: "managedCopy", kind: "value", memberKey: "clr:Content" },
      { type: "copy", text: "Content" },
      { type: "managedCopy", kind: "path", memberKey: "clr:Content" },
      { type: "managedRead", memberKey: "clr:Content" },
    ]));
    // An object value can also be expanded in place; the same row menu carries that item enabled.
    contextmenu(view.doc.querySelector('[data-name="CLR Parent"]') as Element);
    expect(enabled()).toContain("Expand");
    expect(view.errors).toEqual([]);
  });

  it("3.7 lists fields with their values on the Fields tab", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    expect(view.headings()).toEqual(["Fields"]);
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
    expect(view.text("#sidebar-rows")).toContain("System.Void; System.Windows.UIElement; public; instance");
    expect(view.doc.querySelector("#sidebar-rows details")).not.toBeNull();
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
const contextmenuOn = (view: ReturnType<typeof open>, target: Element) => {
  const event = new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
};
const key = (view: ReturnType<typeof open>, target: Element, init: KeyboardEventInit) => {
  const event = new view.dom.window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
};
const menuItems = (view: ReturnType<typeof open>) => [...view.doc.querySelectorAll<HTMLButtonElement>("#sidebar-row-menu button")];
const ALL_ITEMS = ["Copy value", "Copy name", "Copy locator key", "Expand", "Read again", "Show in Basic view"];

describe("Properties sidebar review fixes", () => {
  it("1. draws the menu glyphs as the kebab icon with a name and a tooltip, never a literal question mark", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    const summary = view.doc.querySelector("#sidebar-actions > summary") as HTMLElement;
    expect(summary.querySelector(".codicon-kebab-horizontal")).not.toBeNull();
    expect(summary.getAttribute("aria-label")).toBe("Properties actions");
    expect(summary.title).toBe("Properties actions");
    expect(summary.textContent).toBe("");
    const buttons = [...view.doc.querySelectorAll<HTMLButtonElement>("#sidebar-rows .row-menu-button")];
    expect(buttons.length).toBe(rowsOf(view).length);
    for (const button of buttons) {
      expect(button.querySelector(".codicon-kebab-horizontal")).not.toBeNull();
      expect(button.getAttribute("aria-label")).toBe("Row actions");
      expect(button.title).toBe("Row actions");
      expect(button.textContent).toBe("");
    }
    expect(view.text("#sidebar-inspector")).not.toMatch(/(^|\s)\?(\s|$)/);
    // No source that draws the sidebar or its messages stands in a question mark for a glyph or an ellipsis.
    for (const file of ["media/spy/spy.js", "media/spy/spy.html", "src/spy/spyView.ts", "src/spy/managedPanel.ts"]) {
      const source = readFileSync(file, "utf8");
      expect(source, file).not.toMatch(/managedNode\("summary", "\?"\)|>\?<\/summary>|preview\?"|(?:Loading|Capturing|Refreshing|Checking) [a-z ]+\?["'`]/);
    }
    expect(view.errors).toEqual([]);
  });

  it("2. opens the row menu from the context menu of every row, in Basic and Advanced, and on the Fields tab", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    const check = () => {
      const rows = rowsOf(view);
      expect(rows.length).toBeGreaterThan(0);
      for (const row of rows) {
        expect(contextmenuOn(view, row).defaultPrevented, row.dataset.key).toBe(true);
        expect(view.hiddenReason("#sidebar-row-menu")).toBeUndefined();
        expect(menuItems(view).map((button) => button.textContent), row.dataset.key).toEqual(ALL_ITEMS);
        key(view, view.doc.querySelector("#sidebar-row-menu") as Element, { key: "Escape" });
      }
    };
    check();
    expect(view.names()).toHaveLength(9);
    (view.doc.querySelector("#sidebar-mode") as HTMLButtonElement).click();
    check();
    (view.doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
    check();
    expect(view.errors).toEqual([]);
  });

  it("2. disables the items that do not apply instead of leaving them out", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    const disabled = (name: string) => {
      contextmenuOn(view, view.doc.querySelector(`[data-name="${name}"]`) as Element);
      const result = menuItems(view).filter((button) => button.disabled).map((button) => button.textContent);
      key(view, view.doc.querySelector("#sidebar-row-menu") as Element, { key: "Escape" });
      return result;
    };
    // A Standard row has no member to read, expand or key; its value and name still copy.
    expect(disabled("Height")).toEqual(["Copy locator key", "Expand", "Read again", "Show in Basic view"]);
    // A plain .NET property can be read again and pinned, but is not an object to expand.
    expect(disabled("Content")).toEqual(["Expand"]);
    // An object value expands, but there is no scalar to copy.
    expect(disabled("CLR Parent")).toEqual(["Copy value"]);
    expect(view.errors).toEqual([]);
  });

  it("2. opens from the button, Shift+F10 and the Menu key; arrows move, Esc closes and focus returns to the row", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    const row = view.doc.querySelector('[data-name="Content"]') as HTMLElement;
    const menu = view.doc.querySelector("#sidebar-row-menu") as HTMLElement;
    const button = row.querySelector(".row-menu-button") as HTMLButtonElement;
    button.click();
    expect(menu.hidden).toBe(false);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(view.doc.activeElement?.textContent).toBe("Copy value");
    key(view, menu, { key: "ArrowDown" });
    expect(view.doc.activeElement?.textContent).toBe("Copy name");
    key(view, menu, { key: "ArrowUp" });
    key(view, menu, { key: "ArrowUp" });
    // Wraps past the first item to the last enabled one (Expand is disabled for a string).
    expect(view.doc.activeElement?.textContent).toBe("Show in Basic view");
    key(view, menu, { key: "Home" });
    expect(view.doc.activeElement?.textContent).toBe("Copy value");
    key(view, menu, { key: "End" });
    expect(view.doc.activeElement?.textContent).toBe("Show in Basic view");
    key(view, menu, { key: "Escape" });
    expect(menu.hidden).toBe(true);
    expect(view.doc.activeElement).toBe(row);
    expect(button.hasAttribute("aria-expanded")).toBe(false);
    expect(key(view, row, { key: "F10", shiftKey: true }).defaultPrevented).toBe(true);
    expect(menu.hidden).toBe(false);
    key(view, menu, { key: "Escape" });
    expect(key(view, row, { key: "ContextMenu" }).defaultPrevented).toBe(true);
    expect(menu.hidden).toBe(false);
    // Enter on a focused item runs it (a button's own activation) and closes the menu.
    (view.doc.activeElement as HTMLButtonElement).click();
    expect(menu.hidden).toBe(true);
    expect(view.doc.activeElement).toBe(row);
    expect(view.errors).toEqual([]);
  });

  it("2. keeps the browser's own menu for the argument boxes of a method", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    (view.doc.querySelector('[data-sidebar-tab="methods"]') as HTMLButtonElement).click();
    view.send(managed({ sequence: 2, methods: { status: "ready", canInvoke: true, items: [{ key: "k", name: "Measure", declaringType: "T", returnType: "System.Void", visibility: "public", isStatic: false, parameters: [{ name: "width", type: "System.Double" }] }] } }));
    const input = view.doc.querySelector("#sidebar-rows input") as HTMLInputElement;
    expect(contextmenuOn(view, input).defaultPrevented).toBe(false);
    const row = view.doc.querySelector('#sidebar-rows [data-name^="Measure"]') as Element;
    expect(contextmenuOn(view, row).defaultPrevented).toBe(true);
    expect(menuItems(view).map((button) => button.textContent)).toEqual(ALL_ITEMS);
  });

  it("3. shows a value for every .NET row, dependency and attached properties included, or the real reason", () => {
    const dependency = (name: string) => ({ memberKey: `dp:${name}`, name, category: "dependencyProperty", visibility: "public", readable: true, pathSegment: { kind: "dependency", name, ownerType: "System.Windows.Controls.TextBox", ownerAssembly: "PresentationFramework" }, declaringType: "System.Windows.Controls.TextBox", declaredType: "System.Boolean" });
    const attached = (name: string) => ({ ...dependency(name), memberKey: `ap:${name}`, category: "attachedProperty" });
    const view = open("properties-view", { sidebarAdvanced: true });
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
    expect(view.value("Throws")).toBe("(threw InvalidOperationException)");
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
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession().slice(0, 7));
    view.send(managed({ sequence: 2, rows: [{ member: member("Content"), autoStatus: "declined" }] }));
    expect(view.value("Content")).toBe("Not read (automatic reading is off)");
  });

  it("4. derives Exists, Left and Top, shows AutomationId as empty, and says when MappedName has no page", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
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
    expect(view.value("MappedName")).toBe("(not defined in any page)");
    // Nothing in this row may still read Unknown for a value the page can derive.
    for (const name of ["Exists", "Left", "Top", "AutomationId", "MappedName"]) expect(view.value(name), name).not.toBe("Unknown");
    // The window itself reports its place on the screen.
    view.send({ type: "selected", nodeId: "win", properties: { ...presenterProperties, info: win.info, ancestors: [] } });
    expect(view.value("Left")).toBe("100");
    expect(view.value("Top")).toBe("50");
    // The meaning is documented in the Description pane.
    (view.doc.querySelector('[data-name="Left"]') as HTMLElement).click();
    expect(view.text("#sidebar-description-content")).toContain("containing window");
    expect(view.errors).toEqual([]);
  });

  it("4. takes AutomationId from the element when the property map has none", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    const { AutomationId, ...rest } = presenterProperties.properties;
    void AutomationId;
    view.send({ type: "selected", nodeId: "presenter", properties: { ...presenterProperties, info: { ...presenterNode.info, automationId: "save" }, properties: rest } });
    expect(view.value("AutomationId")).toBe("save");
    expect(view.names().filter((name) => name === "AutomationId")).toHaveLength(1);
    view.send({ type: "selected", nodeId: "presenter", properties: { ...presenterProperties, properties: rest } });
    expect(view.value("AutomationId")).toBe('""');
  });

  it("5. hides the refresh counts in the sidebar and keeps them in the Spy panel", () => {
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
    expect(sidebar.text("#refresh-counts")).toContain("Refresh:");
    expect((sidebar.doc.querySelector("#refresh-counts") as HTMLElement).hidden).toBe(false);
    expect(sidebar.hiddenReason("#refresh-counts")).toContain("display:none");
    expect(panel.errors.concat(sidebar.errors)).toEqual([]);
  });

  it("6. gives the name column room and an ellipsis with a tooltip, and lets values wrap", () => {
    const rule = (selector: string) => css.split("}").find((block) => block.includes(selector)) ?? "";
    const names = rule('.sidebar-table tbody th[scope="row"]');
    expect(names).toMatch(/width:\s*45%/);
    expect(names).toMatch(/min-width:\s*min\(calc\(var\(--name-ch\) \* 1ch\), 60%\)/);
    expect(names).toMatch(/max-width:\s*24ch/);
    expect(names).toMatch(/text-overflow:\s*ellipsis/);
    expect(names).toMatch(/white-space:\s*nowrap/);
    // A name is never broken in the middle of a word; values wrap.
    expect(names).not.toMatch(/overflow-wrap|word-break/);
    expect(rule(".sidebar-table tbody td")).toMatch(/overflow-wrap:\s*anywhere/);
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    const table = view.doc.querySelector("#sidebar-table") as HTMLElement;
    // The column is as wide as the longest name, up to 24 characters.
    const longest = Math.max(...rowsOf(view).map((row) => (row.dataset.name ?? "").length));
    expect(table.style.getPropertyValue("--name-ch")).toBe(String(Math.min(24, Math.max(6, longest))));
    for (const row of rowsOf(view)) expect((row.querySelector("th") as HTMLElement).title).toBe(row.dataset.name);
    expect(view.errors).toEqual([]);
  });

  it("7. shows the metadata of the row that was clicked, and what a Standard row means", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    expect(view.text("#sidebar-description-content")).toBe("Select a row to see its description.");
    (view.doc.querySelector('[data-name="Content"]') as HTMLElement).click();
    const text = () => view.text("#sidebar-description-content");
    for (const line of ["Name: Content", "Value: Hello", "Declared type: System.Object", "Runtime type: System.String", "Declaring type: System.Windows.Controls.ContentPresenter", "Category: clrProperty"]) expect(text()).toContain(line);
    expect(text()).not.toContain("Select a row");
    expect((view.doc.querySelector('[data-name="Content"]') as HTMLElement).getAttribute("aria-current")).toBe("true");
    (view.doc.querySelector('[data-name="Enabled"]') as HTMLElement).click();
    expect(text()).toContain("Name: Enabled");
    expect(text()).toContain("Meaning: Whether the control accepts input");
    expect(view.doc.querySelectorAll('#sidebar-rows [aria-current="true"]')).toHaveLength(1);
    // A value source and a binding appear when the row has them.
    view.send(managed({
      sequence: 2,
      bindings: [{ memberKey: "dp:Text", kind: "Binding", status: "active", path: "Title" }],
      rows: [{ member: { memberKey: "dp:Text", name: "Text", category: "dependencyProperty", visibility: "public", readable: true, pathSegment: { kind: "dependency", name: "Text", ownerType: "T", ownerAssembly: "A" }, declaringType: "T", declaredType: "System.String" }, value: { status: "ok", kind: "string", scalar: "x", runtimeType: "System.String", dependencySource: { baseValueSource: "Local" } } }],
    }));
    (view.doc.querySelector('[data-name="Text"]') as HTMLElement).click();
    expect(text()).toContain("Value source: Local");
    expect(text()).toContain("Binding: Binding; active; Title");
    // Redraws while values arrive keep the description of the selected row, with its fresh value.
    view.send(managed({ sequence: 3, rows: [{ member: { memberKey: "dp:Text", name: "Text", category: "dependencyProperty", visibility: "public", readable: true, pathSegment: { kind: "dependency", name: "Text", ownerType: "T", ownerAssembly: "A" }, declaringType: "T", declaredType: "System.String" }, value: { status: "ok", kind: "string", scalar: "changed", runtimeType: "System.String" } }] }));
    expect(text()).toContain("Value: changed");
    expect(view.errors).toEqual([]);
  });

  it("7. describes a row clicked on its name cell, through the table body", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    const stale = view.doc.querySelector('[data-name="Name"]') as HTMLElement;
    // A redraw replaces the rows; the handlers belong to the table body, so a click on the new row still counts.
    view.send(managed({ sequence: 2 }));
    expect(stale.isConnected).toBe(false);
    (view.doc.querySelector('[data-name="Name"] th') as HTMLElement).click();
    expect(view.text("#sidebar-description-content")).toContain("Name: Name");
  });

  it("keeps Basic mode to exactly the nine rows, each with a menu button", () => {
    const view = open("properties-view");
    view.send(...hostSession());
    expect(view.names()).toEqual(["Enabled", "Height", "MappedName", "Name", "Parent", "Visible", "Width", "ClrFullClassName", "WPFControlText"]);
    expect(view.doc.querySelectorAll("#sidebar-rows .row-menu-button")).toHaveLength(9);
  });

  it("does not redraw rows under an open menu, and applies the redraw when it closes", () => {
    const view = open("properties-view", { sidebarAdvanced: true });
    view.send(...hostSession());
    const row = view.doc.querySelector('[data-name="Content"]') as HTMLElement;
    contextmenuOn(view, row);
    view.send(managed({ sequence: 2, rows: [{ member: member("Content"), value: { status: "ok", kind: "string", scalar: "Later", runtimeType: "System.String" } }] }));
    expect(row.isConnected).toBe(true);
    expect(view.value("Content")).toBe("Hello");
    key(view, view.doc.querySelector("#sidebar-row-menu") as Element, { key: "Escape" });
    expect(view.value("Content")).toBe("Later");
    expect(view.doc.activeElement).toBe(view.doc.querySelector('[data-name="Content"]'));
  });
});
