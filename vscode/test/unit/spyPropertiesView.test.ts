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
    const row = view.doc.querySelector('#sidebar-rows [data-name^="Measure"]') as Element;
    expect(contextmenuOn(view, row).defaultPrevented).toBe(true);
    expect(menuItems(view).map((button) => button.textContent)).toEqual(["Invoke\u2026", ...ALL_ITEMS]);
    menuItems(view)[0]!.click();
    const input = view.doc.querySelector("#sidebar-rows input") as HTMLInputElement;
    expect(contextmenuOn(view, input).defaultPrevented).toBe(false);
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
    contextmenuOn(view, rowFor(view, label));
    return menuItems(view).find((button) => button.textContent === "Invoke\u2026") as HTMLButtonElement;
  };
  const field = (view: ReturnType<typeof open>, index: number) => view.doc.getElementById(`invoke-arg-${index}`) as HTMLInputElement;
  const typeInto = (view: ReturnType<typeof open>, index: number, text: string) => view.type(field(view, index), text);
  const submit = (view: ReturnType<typeof open>) => view.doc.getElementById("invoke-submit") as HTMLButtonElement;
  const forms = (view: ReturnType<typeof open>) => view.doc.querySelectorAll("#sidebar-rows tr.invoke-row");
  const invocations = (view: ReturnType<typeof open>) => view.posts.filter((post) => post.type === "managedInvoke");

  it("offers Invoke\u2026 first in the row menu, enabled when the session can call, the list is ready and the method is supported", () => {
    const view = methodsView();
    const item = invokeItem(view);
    expect(menuItems(view).map((button) => button.textContent)).toEqual(["Invoke\u2026", ...ALL_ITEMS]);
    expect(item.disabled).toBe(false);
    expect(item.title).toBe("");
    expect(view.doc.activeElement).toBe(item);
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
      contextmenuOn(view, row);
      const item = menuItems(view).find((button) => button.textContent === "Invoke\u2026") as HTMLButtonElement;
      expect(item.disabled, name).toBe(true);
      expect(item.title, name).toBe(tooltip);
      expect(menuItems(view).filter((button) => !button.disabled)[0]?.textContent, name).toBe("Copy value");
      expect(view.errors).toEqual([]);
    }
  });

  it("shows the Methods value as the return type and flags only, with the rest in the tooltip and the description", () => {
    const view = methodsView([method({ name: "Hidden", visibility: "private", isStatic: true, returnType: "System.Void", parameters: [{ name: "x", type: "App.Thing", isOut: false }], unsupportedReason: "A parameter type is not supported." }), method({ key: "k2", name: "Both", visibility: "protectedInternal", parameters: [] })]);
    const hidden = rowFor(view, "Hidden(App.Thing x)");
    expect((hidden.children[1] as HTMLElement).textContent).toBe("System.Void private static");
    expect((hidden.children[1] as HTMLElement).title).toBe("WinTestKit.Fixture.FixtureControl\nA parameter type is not supported.");
    expect(view.text("#sidebar-rows")).not.toContain("A parameter type is not supported.");
    expect(view.text("#sidebar-rows")).not.toContain("WinTestKit.Fixture.FixtureControl");
    expect(view.value("Both()")).toBe("System.String protected internal instance");
    hidden.click();
    const description = view.text("#sidebar-description-content");
    for (const line of ["Declaring type: WinTestKit.Fixture.FixtureControl", "Returns: System.Void", "Access: private static", "Not supported: A parameter type is not supported.", "Invocation: Invocation unavailable: A parameter type is not supported."]) expect(description).toContain(line);
    expect(view.errors).toEqual([]);
  });

  it("opens an inline form under the method, one labelled input per parameter, and closes it on Cancel", () => {
    const view = methodsView();
    expect(forms(view)).toHaveLength(0);
    invokeItem(view).click();
    expect((view.doc.getElementById("sidebar-row-menu") as HTMLElement).hidden).toBe(true);
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

  it("shows the result inline under the row, and in the Description pane", () => {
    const view = methodsView();
    invokeItem(view).click();
    view.send(snapshot([method()], { invocation: { key: "k1", text: "Result: written-1" } }, 3));
    const result = view.doc.querySelector("#sidebar-rows tr.invoke-result") as HTMLElement;
    expect(result.textContent).toBe("Result: written-1");
    expect(result.previousElementSibling).toBe(forms(view)[0]);
    expect(view.doc.querySelector("#sidebar-rows details")).toBeNull();
    // The description of the method shows it too (the menu already described the row).
    expect(view.text("#sidebar-description-content")).toContain("Result: written-1");
    // With the form closed, the result stays directly under the method row.
    key(view, field(view, 0), { key: "Escape" });
    expect(rowFor(view).nextElementSibling?.textContent).toBe("Result: written-1");
    // A failure is shown the same way, and only under the method it belongs to.
    view.send(snapshot([method(), method({ key: "k9", name: "Other", parameters: [] })], { invocation: { key: "k1", text: "Invocation failed or timed out. The method may still have had an effect." } }, 4));
    expect(view.doc.querySelectorAll("#sidebar-rows tr.invoke-result")).toHaveLength(1);
    rowFor(view).click();
    expect(view.text("#sidebar-description-content")).toContain("Outcome: Invocation failed or timed out.");
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

  it("is reachable from the keyboard: Shift+F10 opens the menu on Invoke\u2026 and Enter opens the form", () => {
    const view = methodsView();
    const row = rowFor(view);
    row.focus();
    expect(key(view, row, { key: "F10", shiftKey: true }).defaultPrevented).toBe(true);
    expect(view.doc.activeElement?.textContent).toBe("Invoke\u2026");
    (view.doc.activeElement as HTMLButtonElement).click();
    expect(view.doc.activeElement).toBe(field(view, 0));
    expect(forms(view)).toHaveLength(1);
  });
});

describe("Not read rows", () => {
  const dotnet = (rows: unknown[], extra: Record<string, unknown> = {}) => managed({ sequence: 2, rows, ...extra });
  const hidden = (name: string, extra: Record<string, unknown> = {}) => ({ ...member(name), visibility: "internal", readable: false, reason: "nonPublic", ...extra });
  const advanced = () => {
    const view = open("properties-view", { sidebarAdvanced: true });
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
      { member: hidden("Shared", { visibility: "public", reason: "static" }) },
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
    expect(view.value("Shared")).toBe("Not readable: static member");
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
    // 63 members and the ClrFullClassName row every WPF object gets.
    expect(cells.length).toBe(64);
    expect(cells.filter((text) => text === "Not read")).toEqual([]);
    expect(cells.filter((text) => text?.startsWith("Not readable: "))).toHaveLength(40);
    // Declined consent changes nothing for rows that could never be read; the readable ones say reading is off.
    view.send(dotnet([{ member: hidden("HasComplexContent"), autoStatus: "declined" }, { member: member("Text"), autoStatus: "declined" }], { sequence: 3 }));
    expect(view.value("HasComplexContent")).toBe("Not readable: internal member, only public members are read");
    expect(view.value("Text")).toBe("Not read (automatic reading is off)");
  });
});
