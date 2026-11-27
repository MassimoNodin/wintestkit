import { readFileSync } from "node:fs";
import { JSDOM, VirtualConsole } from "jsdom";
import { expect, it } from "vitest";
import { DEFAULT_BASIC_PROPERTIES } from "../../src/spy/basicProperties";

it("expands a WPF window and displays an attachment failure", () => {
  const errors: Error[] = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(error));
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only", virtualConsole });
  const posts: unknown[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval((readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8")));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const root = { nodeId: "window", source: "wpf", hasChildren: true, info: { controlType: "Window", name: "Fixture", processId: 42 } };
  send({ type: "roots", nodes: [root] });
  (dom.window.document.querySelector('[data-node-id="window"] .toggle') as HTMLButtonElement).click();
  expect(posts).toContainEqual({ type: "expand", nodeId: "window" });
  send({ type: "children", nodeId: "window", nodes: [], blocked: { code: "attachFailed", hint: "Inspector unavailable" } });
  expect(dom.window.document.querySelector("#tree")?.textContent).toContain("Inspector unavailable");
  const retry = [...dom.window.document.querySelectorAll("#tree button")].find((button) => button.textContent === "Retry");
  (retry as HTMLButtonElement | undefined)?.click();
  expect(posts).toContainEqual({ type: "treeAttach", nodeId: "window" });
  expect(posts).toContainEqual(expect.objectContaining({ type: "expandedPaths", paths: expect.arrayContaining([[{ controlType: "Process", name: "Fixture", automationId: "process:fixture", className: "" }, { controlType: "Window", name: "Fixture", automationId: "", className: "" }]]) }));
  expect(errors).toEqual([]);
  dom.window.close();
});

it("renders returned visual children in the Spy tree", () => {
  const errors: Error[] = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(error));
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only", virtualConsole });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval((readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8")));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const info = { controlType: "Window", name: "Fixture", processId: 42 };
  send({ type: "roots", nodes: [{ nodeId: "window", source: "wpf", hasChildren: true, info }] });
  (dom.window.document.querySelector('[data-node-id="window"] .toggle') as HTMLButtonElement).click();
  send({ type: "wpfDetails", nodeId: "window", missing: false });
  send({ type: "children", nodeId: "window", nodes: [{ nodeId: "child", source: "wpf", hasChildren: true, info: { controlType: "Border", name: "Child" }, identity: { type: "System.Windows.Controls.Border" } }] });
  expect(dom.window.document.querySelector('[data-node-id="child"]')?.textContent).toContain("Border");
  expect(errors).toEqual([]);
  dom.window.close();
});

it("rebuilds expanded branches and clears old selections when roots are replaced", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "properties-view"), { runScripts: "outside-only" });
  const posts: unknown[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval((readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8")));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const info = { controlType: "Window", name: "App", processId: 42 };
  const root = (nodeId: string) => ({ nodeId, source: "wpf", hasChildren: true, info });
  const child = (nodeId: string) => ({ nodeId, source: "wpf", hasChildren: false, info: { controlType: "Button", name: "Save" } });
  send({ type: "roots", nodes: [root("old")] });
  (dom.window.document.querySelector('[data-node-id="old"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "old", nodes: [child("old-child")] });
  // The side panel mirrors the tree; it never reports expansion or asks for children itself.
  expect(posts.map((post) => (post as { type: string }).type)).toEqual(["propertiesReady"]);
  send({ type: "selected", nodeId: "old-child", properties: { source: "wpf", info: child("old-child").info, properties: {} } });
  send({ type: "objectPreview", nodeId: "old-child", reason: "Inspector session ended. Reconnecting" });
  expect(dom.window.document.querySelector("#object-preview-status")?.textContent).toContain("Reconnecting");
  send({ type: "roots", nodes: [root("new")] });
  expect(dom.window.document.querySelector('[data-node-id="old-child"]')).toBeNull();
  send({ type: "children", nodeId: "new", nodes: [child("new-child")], expanded: true });
  send({ type: "selected", nodeId: "new-child", properties: { source: "wpf", info: child("new-child").info, properties: {} } });
  send({ type: "selectionRestored", nodeId: "new-child" });
  send({ type: "objectPreview", nodeId: "new-child", reason: "Capture unavailable. Retry." });
  expect(dom.window.document.querySelector('[data-node-id="new-child"]')).not.toBeNull();
  expect(dom.window.document.querySelector("#selection-name")?.textContent).toBe("Save");
  expect(dom.window.document.querySelector("#object-preview-status")?.textContent).toContain("Retry");
  dom.window.close();
});


it("offers an upgrade while compatibility blocks Spy", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  const posts: unknown[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval((readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8")));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  send({ type: "compatibilityBlocked", message: "Package is too old", label: "Upgrade now" });
  const button = dom.window.document.querySelector("#upgrade-package") as HTMLButtonElement;
  expect(dom.window.document.querySelector("#tree-empty")?.textContent).toContain("Package is too old");
  expect(button.hidden).toBe(false);
  expect(button.textContent).toBe("Upgrade now");
  button.click();
  expect(posts).toContainEqual({ type: "upgradePackage" });
  send({ type: "roots", nodes: [] });
  expect(button.hidden).toBe(true);
  dom.window.close();
});


it("renders managed failure codes and hints", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "properties-view"), { runScripts: "outside-only" });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval((readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8")));
  for (const [code, state, hint] of [["alreadyAttached", "attach failed", "Another session owns the agent."], ["inspectorDisabled", "not enabled", "Enable the inspector."], ["newCode", "attach failed", "Unknown reason."]]) {
    dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data: { type: "managedPanel", sequence: 1, visible: true, state, failure: { code, hint, message: "failure" } } }));
    expect(dom.window.document.querySelector("#managed-state")?.textContent).toBe(`${state.charAt(0).toUpperCase() + state.slice(1)}: ${code}.`);
    expect(dom.window.document.querySelector("#managed-explanation")?.textContent).toBe(`${hint} Run ` + "`wtk doctor --agent`" + " for details.");
  }
  dom.window.close();
});

it("groups windows and keeps process rows when windows change", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  const posts: { type: string; nodeId?: string; path?: unknown[] }[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: typeof posts[number]) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const win = (nodeId: string, pid: number, name: string) => ({ nodeId, hasChildren: true, info: { controlType: "Window", name, className: "Window", processId: pid, processName: "Fixture.exe" } });
  const a = win("a", 42, "First"), b = win("b", 42, "Second"), c = win("c", 9, "Other"), u = win("u", 0, "Unknown");
  send({ type: "roots", nodes: [a, b, c, u] });
  const process = doc.querySelector('[data-node-id="process:42"]')!;
  expect(process.textContent).toContain('Process("Fixture.exe")');
  expect(process.textContent).toContain("PID 42");
  expect(process.getAttribute("aria-level")).toBe("1");
  expect(doc.querySelector('[data-node-id="a"]')?.getAttribute("aria-level")).toBe("2");
  expect(doc.querySelector('[data-node-id="b"]')?.getAttribute("aria-setsize")).toBe("2");
  expect(doc.querySelector('[data-node-id="process:0"]')?.textContent).toContain('Process("unknown")');
  expect(doc.querySelectorAll('#tree > li')).toHaveLength(3);
  dom.window.HTMLElement.prototype.getClientRects = () => [new dom.window.DOMRect()] as unknown as DOMRectList;
  const key = (row: Element, value: string) => row.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: value, bubbles: true }));
  (process as HTMLElement).focus();
  key(process, "ArrowRight");
  expect(doc.activeElement?.getAttribute("data-node-id")).toBe("a");
  key(doc.activeElement!, "ArrowLeft");
  expect(doc.activeElement).toBe(process);
  key(process, "End");
  expect(doc.activeElement?.getAttribute("data-node-id")).toBe("u");
  key(doc.activeElement!, "Home");
  expect(doc.activeElement).toBe(process);
  send({ type: "rootIcons", icons: { 42: "data:image/png;base64,AAAA" } });
  const image = process.querySelector("img")!; image.dispatchEvent(new dom.window.Event("load")); expect(image.hidden).toBe(false);
  posts.length = 0;
  (process.querySelector(".label") as HTMLButtonElement).click();
  expect(posts).toEqual([{ type: "select", nodeId: "process:42" }]);
  expect(doc.querySelector("#selection-name")?.textContent).toBe("Process: Fixture, PID 42, 2 windows");
  expect((doc.querySelector("#generate") as HTMLButtonElement).disabled).toBe(true);
  (process.querySelector(".toggle") as HTMLButtonElement).click();
  const search = doc.querySelector("#search") as HTMLInputElement; search.value = "Second"; search.dispatchEvent(new dom.window.Event("input"));
  expect(process.getAttribute("aria-expanded")).toBe("true");
  search.value = ""; search.dispatchEvent(new dom.window.Event("input"));
  send({ type: "children", nodeId: "a", nodes: [], expanded: true });
  expect(process.getAttribute("aria-expanded")).toBe("true");
  (doc.querySelector('[data-node-id="b"] .label') as HTMLButtonElement).click();
  expect(posts.find((post) => post.type === "select" && post.nodeId === "b")?.path?.[0]).toEqual({ controlType: "Process", automationId: "process:fixture", name: "Fixture", className: "" });
  send({ type: "roots", nodes: [b, c, u] });
  expect(doc.querySelector('[data-node-id="process:42"]')).toBe(process);
  expect(doc.querySelector('[data-node-id="a"]')).toBeNull();
  send({ type: "roots", nodes: [c, u] });
  expect(doc.querySelector('[data-node-id="process:42"]')).toBeNull();
  dom.window.close();
});


it("preserves rows and reports counts for an unchanged refresh", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  const posts: unknown[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const root = { nodeId: "window", hasChildren: true, info: { controlType: "Window", name: "Fixture", processId: 42 } };
  const child = { nodeId: "child", hasChildren: false, info: { controlType: "Button", name: "Save" } };
  send({ type: "roots", nodes: [root] });
  (doc.querySelector('[data-node-id="window"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "window", nodes: [child] });
  const row = doc.querySelector('[data-node-id="child"]');
  const scroller = doc.querySelector("#tree-region") as HTMLElement;
  scroller.scrollTop = 33;
  send({ type: "rootsDiff", nodes: [root], revision: 1, refresh: true });
  expect(posts).toContainEqual({ type: "refreshChildren", nodeId: "window", revision: 1 });
  send({ type: "childrenDiff", nodeId: "window", nodes: [child], revision: 1 });
  expect(doc.querySelector('[data-node-id="child"]')).toBe(row);
  expect(scroller.scrollTop).toBe(33);
  expect(JSON.parse((doc.querySelector("#tree") as HTMLElement).dataset.refreshCounts!)).toEqual({ added: 0, removed: 0, kept: 3, redrawn: 0 });
  expect((doc.querySelector("#refresh-counts") as HTMLElement).hidden).toBe(true);
  send({ type: "state", hasProject: true, showRefreshCounts: true });
  expect((doc.querySelector("#refresh-counts") as HTMLElement).hidden).toBe(false);
  send({ type: "rootsDiff", nodes: [root], revision: 2, refresh: true });
  send({ type: "childrenDiff", nodeId: "window", nodes: [{ ...child, info: { ...child.info, name: "Changed" } }, { ...child, nodeId: "new" }], revision: 2 });
  expect(doc.querySelector('[data-node-id="child"]')).toBe(row);
  expect(row?.textContent).toContain("Changed");
  expect(doc.querySelectorAll('[data-node-id="new"]')).toHaveLength(1);
  send({ type: "rootsDiff", nodes: [], revision: 3, refresh: true });
  expect(doc.querySelector('[data-node-id="process:42"]')).toBeNull();
  dom.window.close();
});


it("applies server sibling order without recreating rows", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const root = { nodeId: "window", hasChildren: true, info: { controlType: "Window", name: "Fixture", processId: 42 } };
  const item = (nodeId: string) => ({ nodeId, hasChildren: false, info: { controlType: "ListBoxItem", name: nodeId } });
  send({ type: "roots", nodes: [root] });
  (doc.querySelector('[data-node-id="window"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "window", nodes: [item("a"), item("b"), item("c")] });
  const rows = ["a", "b", "c"].map((id) => doc.querySelector(`[data-node-id="${id}"]`));
  send({ type: "rootsDiff", nodes: [root], revision: 1, refresh: true });
  send({ type: "childrenDiff", nodeId: "window", nodes: [item("c"), item("a"), item("b")], revision: 1 });
  const ordered = Array.from(doc.querySelectorAll('[data-node-id="a"], [data-node-id="b"], [data-node-id="c"]'));
  expect(ordered.map((row) => row.getAttribute("data-node-id"))).toEqual(["c", "a", "b"]);
  expect(ordered[0]).toBe(rows[2]);
  expect(ordered[1]).toBe(rows[0]);
  expect(ordered[2]).toBe(rows[1]);
  dom.window.close();
});

it("diffs siblings and drops removed subtrees without replacing surviving rows", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  const posts: { type: string; nodeId?: string }[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: typeof posts[number]) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const win = (id: string) => ({ nodeId: id, hasChildren: true, info: { controlType: "Window", name: id, processId: 42 } });
  const button = (id: string) => ({ nodeId: id, hasChildren: false, info: { controlType: "Button", name: "Save" } });
  send({ type: "roots", nodes: [win("a"), win("b")] });
  (doc.querySelector('[data-node-id="a"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "a", nodes: [button("first")] });
  (doc.querySelector('[data-node-id="first"] .label') as HTMLButtonElement).click();
  send({ type: "selected", nodeId: "first", properties: { info: button("first").info, properties: {} } });
  const first = doc.querySelector('[data-node-id="first"]');
  const process = doc.querySelector('[data-node-id="process:42"]');
  posts.length = 0;
  send({ type: "rootsDiff", nodes: [win("a"), win("c")], revision: 1, refresh: true });
  send({ type: "childrenDiff", nodeId: "a", nodes: [button("new"), button("first")], revision: 1 });
  expect(doc.querySelector('[data-node-id="process:42"]')).toBe(process);
  expect(doc.querySelector('[data-node-id="b"]')).toBeNull();
  expect(doc.querySelectorAll('[data-node-id="c"]')).toHaveLength(1);
  expect(doc.querySelector('[data-node-id="first"]')).toBe(first);
  expect(first?.getAttribute("aria-selected")).toBe("true");
  expect(first?.textContent).toContain('"Save", 2');
  expect(posts.some((message) => message.type === "select")).toBe(false);
  send({ type: "rootsDiff", nodes: [win("c")], revision: 2, refresh: true });
  expect(doc.querySelector('[data-node-id="first"]')).toBeNull();
  expect(posts).toContainEqual({ type: "selectionRemoved" });
  expect(doc.querySelector('[data-node-id="process:42"]')).toBe(process);
  dom.window.close();
});


it("keeps expanded WPF rows across changing identities and incomplete refreshes", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  const posts: unknown[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const root = { nodeId: "window", hasChildren: true, info: { controlType: "Window", name: "App", processId: 42 } };
  const wpf = (nodeId: string, type: string) => ({ nodeId, source: "wpf", hasChildren: true, identity: { type }, info: { controlType: type, name: "" } });
  const border = wpf("border-old", "Border"), adorner = wpf("adorner-old", "AdornerDecorator");
  send({ type: "roots", nodes: [root] });
  (doc.querySelector('[data-node-id="window"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "window", nodes: [border] });
  (doc.querySelector('[data-node-id="border-old"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "border-old", nodes: [adorner] });
  const row = doc.querySelector('[data-node-id="border-old"]');
  send({ type: "rootsDiff", nodes: [root], revision: 1, refresh: true });
  send({ type: "childrenDiff", nodeId: "window", nodes: [wpf("border-new", "Border")], revision: 1 });
  expect(doc.querySelector('[data-node-id="border-new"]')).toBe(row);
  expect(posts).toContainEqual({ type: "refreshChildren", nodeId: "border-new", revision: 1 });
  send({ type: "childrenDiff", nodeId: "border-new", nodes: [wpf("adorner-new", "AdornerDecorator")], revision: 1 });
  expect(doc.querySelector('[data-node-id="adorner-new"]')).not.toBeNull();
  expect(JSON.parse((doc.querySelector("#tree") as HTMLElement).dataset.refreshCounts!)).toEqual({ added: 0, removed: 0, kept: 4, redrawn: 0 });
  for (const [index, result] of [{ nodes: [] }, { nodes: [], blocked: { code: "unavailable", hint: "no" } }, { nodes: [border], nextPageToken: "more" }].entries()) {
    const revision = index + 2;
    send({ type: "rootsDiff", nodes: [root], revision, refresh: true });
    send({ type: "childrenDiff", nodeId: "window", revision, ...result });
    expect(doc.querySelector('[data-node-id="border-new"]')).toBe(row);
    expect(doc.querySelector('[data-node-id="adorner-new"]')).not.toBeNull();
    expect(JSON.parse((doc.querySelector("#tree") as HTMLElement).dataset.refreshCounts!).removed).toBe(0);
  }
  dom.window.close();
});

it("shows only one icon on process rows", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  send({ type: "roots", nodes: [{ nodeId: "window", hasChildren: true, info: { controlType: "Window", name: "App", processId: 42 } }] });
  const process = dom.window.document.querySelector('[data-node-id="process:42"]')!;
  const icon = process.querySelector(".control-icon") as HTMLElement;
  expect(icon.classList.contains("codicon-gear")).toBe(true);
  send({ type: "rootIcons", icons: { 42: "data:image/png;base64,YQ==" } });
  const image = process.querySelector(".app-icon") as HTMLImageElement;
  image.dispatchEvent(new dom.window.Event("load"));
  expect(icon.hidden).toBe(true);
  expect(image.hidden).toBe(false);
  dom.window.close();
});


it("reveals an in-place picked path without replacing other branches", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (callback: () => void) => callback() });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const node = (nodeId: string, controlType: string, name: string, hasChildren: boolean, wpfOrdinal = 1) => ({ nodeId, source: "wpf", hasChildren, info: { controlType, name, processId: 42 }, identity: { type: controlType }, wpfText: name, wpfOrdinal });
  const main = node("main", "Window", "Main", true), duplicate = node("duplicate", "Window", "Duplicate items", true);
  const other = node("other", "Border", "", true), first = node("first", "ListBoxItem", "Beta", true), second = node("second", "ListBoxItem", "Beta", true, 2), text = node("text", "TextBlock", "Beta", false);
  send({ type: "roots", nodes: [main, duplicate] });
  (doc.querySelector('[data-node-id="main"] .toggle') as HTMLButtonElement).click();
  send({ type: "children", nodeId: "main", nodes: [other] });
  const otherRow = doc.querySelector('[data-node-id="other"]');
  send({ type: "rootsDiff", nodes: [main, duplicate], revision: 1 });
  send({ type: "childrenDiff", nodeId: "duplicate", nodes: [first, second], revision: 1 });
  send({ type: "childrenDiff", nodeId: "second", nodes: [text], revision: 1 });
  send({ type: "picked", node: text });
  expect(doc.querySelector('[data-node-id="main"]')?.getAttribute("aria-expanded")).toBe("true");
  expect(doc.querySelector('[data-node-id="other"]')).toBe(otherRow);
  expect(doc.querySelector('[data-node-id="duplicate"]')?.getAttribute("aria-expanded")).toBe("true");
  expect(doc.querySelector('[data-node-id="second"]')?.getAttribute("aria-expanded")).toBe("true");
  expect(doc.querySelector('[data-node-id="text"]')?.getAttribute("aria-selected")).toBe("true");
  // The ordinal is wpf:Ordinal: the agent counted the siblings of the same type.
  expect(doc.querySelector('[data-node-id="first"]')?.textContent).toContain('"Beta", 1');
  expect(doc.querySelector('[data-node-id="second"]')?.textContent).toContain('"Beta", 2');
  dom.window.close();
});


it("does not reconcile ambiguous WPF sibling identities", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "spy-view"), { runScripts: "outside-only" });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (callback: () => void) => callback() });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const root = { nodeId: "root", hasChildren: true, info: { controlType: "Window", name: "App", processId: 42 } };
  const item = (nodeId: string) => ({ nodeId, source: "wpf", hasChildren: true, identity: { type: "System.Windows.Controls.ListBoxItem" }, info: { controlType: "ListBoxItem", name: "" } });
  send({ type: "roots", nodes: [root] });
  send({ type: "children", nodeId: "root", nodes: [item("old-first"), item("old-second")] });
  const first = doc.querySelector('[data-node-id="old-first"]');
  const second = doc.querySelector('[data-node-id="old-second"]');
  send({ type: "rootsDiff", nodes: [root], revision: 1 });
  send({ type: "childrenDiff", nodeId: "root", nodes: [item("new-first"), item("new-second")], revision: 1 });
  expect(doc.querySelector('[data-node-id="old-first"]')).toBe(first);
  expect(doc.querySelector('[data-node-id="old-second"]')).toBe(second);
  expect(doc.querySelector('[data-node-id="new-first"]')).not.toBe(first);
  expect(doc.querySelector('[data-node-id="new-second"]')).not.toBe(second);
  dom.window.close();
});


it("places the live preview first in the sidebar and gates it to that surface", () => {
  const html = readFileSync("media/spy/spy.html", "utf8");
  const css = readFileSync("media/spy/spy.css", "utf8");
  expect(css).toContain("body.spy-view #object-preview { display: none !important; }");
  for (const surface of ["spy-view", "properties-view"]) {
    const dom = new JSDOM(html.replace("{{viewClass}}", surface), { runScripts: "outside-only" });
    const posts: unknown[] = [];
    Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message) }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
    dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
    const doc = dom.window.document;
    expect(doc.querySelector(".properties-scroll")?.firstElementChild?.id).toBe("object-preview");
    const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
    send({ type: "propertiesVisibility", visible: true });
    expect((doc.querySelector("#properties-pane") as HTMLElement).hidden).toBe(surface === "spy-view");
    send({ type: "propertiesVisibility", visible: false });
    expect((doc.querySelector("#properties-pane") as HTMLElement).hidden).toBe(false);
    send({ type: "selected", nodeId: "a", properties: { info: { controlType: "Button", name: "A" }, properties: {} } });
    send({ type: "objectPreview", nodeId: "a", reason: "Unavailable" });
    expect((doc.querySelector("#object-preview") as HTMLElement).hidden).toBe(surface !== "properties-view");
    if (surface === "properties-view") {
      (doc.querySelector("#preview-retry") as HTMLButtonElement).click();
      expect(posts).toContainEqual({ type: "retryPreview" });
      send({ type: "selectionCleared" });
      expect((doc.querySelector("#object-preview") as HTMLElement).hidden).toBe(true);
    }
    dom.window.close();
  }
});

it("renders searchable sidebar tabs and remembers the property mode", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "properties-view"), { runScripts: "outside-only" });
  const posts: unknown[] = []; let state: Record<string, unknown> = { sidebarShowAll: false };
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message), getState: () => state, setState: (next: Record<string, unknown>) => { state = next; } }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const win = { nodeId: "win", source: "wpf", hasChildren: true, info: { controlType: "Window", name: "Fixture", processId: 1 } };
  const child = { nodeId: "child", source: "wpf", hasChildren: false, wpfText: "Save", info: { controlType: "Button", name: "Save", isEnabled: true, rect: { left: 10, top: 20, width: 30, height: 40 } } };
  send({ type: "state", basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES] });
  send({ type: "roots", nodes: [win] });
  send({ type: "children", nodeId: "win", nodes: [child], expanded: true });
  send({ type: "selected", nodeId: "child", properties: { source: "wpf", info: child.info, properties: { ClrFullClassName: "Example.Button", Visible: "True", Custom: "custom value" }, uiaMapped: false } });
  const names = () => [...doc.querySelectorAll<HTMLTableRowElement>("#sidebar-rows tr[data-name]")].map((row) => row.dataset.name);
  expect(names()).toEqual(["Enabled", "Height", "Name", "Parent", "Visible", "Width", "ClrClassName", "ClrFullClassName", "WPFControlName", "WPFControlOrdinalNo", "WPFControlText"]);
  expect(doc.querySelector('[data-name="WPFControlText"] td')?.textContent).toBe("Unknown");
  send({ type: "definitions", nodeId: "child", state: "ready", definitions: [{ kind: "element", qualname: "Page.save", file: "page.py", line: 1, pages: [], pageCount: 1 }] });
  expect(doc.querySelector('[data-name="MappedName"]')).toBeNull();
  (doc.querySelector('[data-name="Parent"] td button') as HTMLButtonElement).click();
  expect(posts).toContainEqual(expect.objectContaining({ type: "select", nodeId: "win" }));
  send({ type: "selected", nodeId: "child", properties: { source: "wpf", info: child.info, properties: { ClrFullClassName: "Example.Button", Custom: "custom value" }, uiaMapped: false } });
  (doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
  expect(state.sidebarShowAll).toBe(true);
  // The label chain starts at the process and is built from the tree.
  const chain = 'Process("Fixture").Window("").WPFObject("Button", "Save")';
  expect(doc.querySelector('[data-name="FullName"] td')?.textContent).toBe(chain);
  expect(posts).toContainEqual({ type: "generateLocator", nodeId: "child" });
  const locator = { unique: true, strategy: "automationId", helpers: [], window: { code: "Window(title='Fixture')" }, code: "Button(automation_id='save')" };
  send({ type: "suggestion", nodeId: "child", suggestion: locator });
  // A suggested locator does not replace the label chain.
  expect(doc.querySelector('[data-name="FullName"] td')?.textContent).toBe(chain);
  send({ type: "selectionPending", nodeId: "win" });
  send({ type: "suggestion", nodeId: "child", suggestion: locator });
  send({ type: "selected", nodeId: "win", properties: { source: "wpf", info: win.info, properties: { WPFControlText: "" }, uiaMapped: false } });
  expect(doc.querySelector('[data-name="FullName"] td')?.textContent).toBe('Process("Fixture").Window("")');
  (doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
  expect(doc.querySelector('[data-name="WPFControlText"] td')?.textContent).toBe("(empty)");
  (doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
  send({ type: "selected", nodeId: "child", properties: { source: "wpf", info: child.info, properties: { ClrFullClassName: "Example.Button", Custom: "custom value" }, uiaMapped: false } });
  expect(doc.querySelector("#sidebar-rows")?.textContent).not.toContain("UI Automation");
  const search = doc.querySelector("#sidebar-search") as HTMLInputElement; search.value = "custom value"; search.dispatchEvent(new dom.window.Event("input"));
  expect(names()).toEqual(["Custom"]);
  send({ type: "managedPanel", sequence: 2, visible: true, state: "ready", object: { objectId: "o", type: { fullName: "Example", assemblyName: "A", baseTypes: [] } }, rows: [{ member: { memberKey: "field:Count", name: "Count", category: "clrField", visibility: "public", readable: true, pathSegment: {}, declaringType: "Example", declaredType: "Int32" }, value: { status: "ok", scalar: 7 } }] });
  (doc.querySelector('[data-sidebar-tab="fields"]') as HTMLButtonElement).click();
  expect(names()).toEqual([]);
  search.value = "7"; search.dispatchEvent(new dom.window.Event("input")); expect(names()).toEqual(["Count"]);
  (doc.querySelector('[data-sidebar-tab="methods"]') as HTMLButtonElement).click();
  expect(posts).toContainEqual({ type: "managedMethods", action: "activate" });
  expect(doc.querySelector("#sidebar-empty")?.textContent).toContain("not loaded");
  const method = { name: "<Run>", declaringType: "Example.Base", returnType: "System.Void", visibility: "public", isStatic: true, unsupportedReason: "generic", parameters: [{ name: "count", type: "System.Int32" }] };
  send({ type: "managedPanel", sequence: 3, visible: true, state: "ready", object: { objectId: "o", type: { fullName: "Example", assemblyName: "A", baseTypes: [] } }, rows: [], methods: { status: "ready", items: [method, { ...method, parameters: [{ name: "text", type: "System.String" }] }], page: { complete: false, nextToken: true } } });
  search.value = ""; search.dispatchEvent(new dom.window.Event("input"));
  expect(names()).toEqual(["<Run>(System.Int32 count)", "<Run>(System.String text)"]);
  expect(doc.querySelector('[data-name="<Run>(System.Int32 count)"] td')?.textContent).toBe("System.Void public static");
  expect(doc.querySelector("#sidebar-rows")?.textContent).not.toContain("generic");
  expect(doc.querySelector("#sidebar-rows img")).toBeNull();
  expect(doc.querySelector("#sidebar-rows")?.textContent).toContain("Partial list");
  [...doc.querySelectorAll<HTMLButtonElement>("#sidebar-rows button")].find((button) => button.textContent === "Load more methods")!.click();
  expect(posts).toContainEqual({ type: "managedMethods", action: "more" });
  search.value = "string"; search.dispatchEvent(new dom.window.Event("input")); expect(names()).toEqual(["<Run>(System.String text)"]);
  search.value = ""; search.dispatchEvent(new dom.window.Event("input"));
  const supported = { ...method, key: "safe-key", unsupportedReason: undefined, parameters: [{ name: "count", type: "System.Int64" }] };
  send({ type: "managedPanel", sequence: 4, visible: true, state: "ready", object: { objectId: "o", type: { fullName: "Example", assemblyName: "A", baseTypes: [] } }, rows: [], methods: { status: "ready", canInvoke: true, items: [supported, method] } });
  // The form is not drawn until the row menu asks for it; the unsupported method offers the item disabled.
  expect(doc.querySelector("#sidebar-rows input")).toBeNull();
  const play = (name: string) => doc.querySelector<HTMLButtonElement>(`[data-name="${name}"] [aria-label="Invoke\u2026"]`)!;
  expect(play("<Run>(System.Int32 count)").disabled).toBe(true);
  const item = play("<Run>(System.Int64 count)"); expect(item.disabled).toBe(false); item.click();
  const input = doc.querySelector<HTMLInputElement>("#sidebar-rows input")!; input.value = "9223372036854775807"; input.dispatchEvent(new dom.window.Event("input"));
  const invoke = doc.getElementById("invoke-submit") as HTMLButtonElement;
  invoke.click(); expect(posts).toContainEqual({ type: "managedInvoke", memberKey: "safe-key", arguments: [{ kind: "value", text: "9223372036854775807" }] });
  expect(doc.querySelectorAll("#sidebar-rows details")).toHaveLength(0);
  send({ type: "managedPanel", sequence: 5, visible: true, state: "ready", object: { objectId: "o", type: { fullName: "Example", assemblyName: "A", baseTypes: [] } }, rows: [], methods: { status: "error", items: [], page: { complete: false, nextToken: true } } });
  [...doc.querySelectorAll<HTMLButtonElement>("#sidebar-rows button")].find((button) => button.textContent === "Retry methods")!.click();
  expect(posts).toContainEqual({ type: "managedMethods", action: "retry" });
  dom.window.close();
});

it("offers managed row actions, tooltips, pins, and readiness controls", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "properties-view"), { runScripts: "outside-only" });
  const posts: unknown[] = []; let state: Record<string, unknown> = { sidebarShowAll: true };
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: unknown) => posts.push(message), getState: () => state, setState: (next: Record<string, unknown>) => { state = next; } }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const doc = dom.window.document;
  const node = { nodeId: "n", source: "wpf", hasChildren: false, info: { controlType: "Button", name: "Save", processId: 1 } };
  send({ type: "roots", nodes: [node] });
  send({ type: "selected", nodeId: "n", properties: { source: "wpf", info: node.info, properties: {} } });
  send({ type: "managedPanel", sequence: 1, visible: true, state: "attach failed", failure: { code: "attachFailed", hint: "Try again" } });
  expect(doc.querySelector("#wpf-details-note")?.textContent).toContain("attachFailed: Try again");
  (doc.querySelector("#wpf-details-attach") as HTMLButtonElement).click(); expect(posts).toContainEqual({ type: "managedAttach" });
  const member = { memberKey: "clr:Title", name: "Title", category: "clrProperty", visibility: "public", readable: true, pathSegment: { kind: "property", name: "Title" }, declaringType: "Example", declaredType: "String" };
  const snapshot = { type: "managedPanel", sequence: 2, visible: true, state: "ready", object: { objectId: "o", type: { fullName: "Example", assemblyName: "A", baseTypes: [] } }, bindings: [{ memberKey: "clr:Title", kind: "Binding", status: "active", path: "Name" }], rows: [{ member, value: { status: "ok", kind: "string", scalar: "Hello", runtimeType: "System.String" } }, { member: { ...member, memberKey: "clr:Secret", name: "Secret", pathSegment: { kind: "property", name: "Secret" } }, value: { status: "redacted", scalar: "secret" } }] };
  send(snapshot);
  expect((doc.querySelector("#wpf-details-note") as HTMLElement).hidden).toBe(true);
  expect((doc.querySelector("#sidebar-actions") as HTMLElement).hidden).toBe(false);
  const row = doc.querySelector('[data-name="Title"]') as HTMLTableRowElement;
  expect(doc.querySelector("#sidebar-description")).toBeNull();
  expect((row.cells[0] as HTMLElement).title).toContain("Runtime type: System.String");
  expect((row.cells[0] as HTMLElement).title).toContain("Binding: Binding; active; Name");
  row.cells[0]!.click(); row.cells[1]!.click();
  expect(posts).toContainEqual({ type: "managedCopy", kind: "value", memberKey: "clr:Title" });
  row.querySelector<HTMLButtonElement>('[aria-label="Read again"]')!.click();
  expect(posts).toContainEqual({ type: "managedRead", memberKey: "clr:Title" });
  expect(doc.querySelector("#sidebar-row-menu, .row-menu-button")).toBeNull();
  const secret = doc.querySelector('[data-name="Secret"]') as HTMLTableRowElement;
  expect(secret.textContent).not.toContain("secret");
  (doc.querySelector("#sidebar-export") as HTMLButtonElement).click(); expect(posts).toContainEqual({ type: "managedCopy", kind: "export" });
  dom.window.close();
});

const spyDom = (viewClass: "spy-view" | "properties-view") => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", viewClass), { runScripts: "outside-only" });
  const posts: { type: string; [key: string]: unknown }[] = [];
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage: (message: { type: string }) => posts.push(message), getState: () => ({}), setState() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  return { dom, doc: dom.window.document, posts, send };
};
// A WPF window row as the host describes it once the agent knows its root visual, and nodes below it.
const windowRow = (nodeId: string, rootType: string, xName: string, title: string, extra: Record<string, unknown> = {}) => ({ nodeId, source: "wpf", windowNode: true, hasChildren: true, info: { controlType: "Window", name: title, className: "HwndWrapper[App;;1]", processId: 42, processName: "App.exe" }, identity: { type: "Fixture." + rootType, ...(xName ? { xName } : {}) }, wpfText: title, ...extra });
const wpfNode = (nodeId: string, type: string, text: string | undefined, wpfOrdinal: number, xName = "", hasChildren = true) => ({ nodeId, source: "wpf", hasChildren, info: { controlType: type, name: text ?? "", processId: 42 }, identity: { type: "System.Windows.Controls." + type, ...(xName ? { xName } : {}) }, ...(text === undefined ? {} : { wpfText: text }), wpfOrdinal });

it("labels WPF windows as window nodes below the process and their root visual as the only child", () => {
  const { doc, send } = spyDom("spy-view");
  const options = windowRow("w1", "SettingsView", "SettingsViewWindow", "Options");
  const plain = windowRow("w2", "MainView", "", "Main title");
  const same = windowRow("w3", "MainView", "", "Other");
  send({ type: "roots", nodes: [options, plain, same] });
  const text = (id: string) => doc.querySelector(`[data-node-id="${id}"] .label`)?.textContent;
  expect(text("process:42")).toContain('Process("App.exe")');
  expect(text("w1")).toContain('WPFObject("HwndSource: SettingsViewWindow", "Options")');
  expect(text("w2")).toContain('WPFObject("HwndSource: MainView", "Main title")');
  expect(text("w3")).toContain('WPFObject("HwndSource: MainView", "Other")');
  send({ type: "children", nodeId: "w1", nodes: [wpfNode("root", "Window", "Options", 1, "SettingsViewWindow")], expanded: true });
  send({ type: "children", nodeId: "root", nodes: [wpfNode("save", "Button", "Save", 1), wpfNode("cancel", "Button", "Cancel", 2)], expanded: true });
  expect(text("root")).toContain('WPFObject("SettingsViewWindow")');
  expect(text("cancel")).toContain('WPFObject("Button", "Cancel")');
  expect(doc.querySelector('[data-node-id="root"]')?.getAttribute("aria-level")).toBe("3");
});

it("marks labels read with template parts shown as not pasteable and tells the host about the toggle", () => {
  const { doc, posts, send } = spyDom("spy-view");
  send({ type: "roots", nodes: [windowRow("w1", "MainView", "", "Main")] });
  send({ type: "children", nodeId: "w1", nodes: [wpfNode("root", "MainView", "Main", 1)], expanded: true });
  const row = doc.querySelector('[data-node-id="root"]')!;
  const button = doc.querySelector<HTMLButtonElement>("#template-parts")!;
  expect(button.getAttribute("aria-pressed")).toBe("false");
  expect(row.classList.contains("unpasteable")).toBe(false);
  button.click();
  expect(posts).toContainEqual({ type: "showTemplateParts", enabled: true });
  send({ type: "state", showTemplateParts: true });
  expect(button.getAttribute("aria-pressed")).toBe("true");
  expect(row.classList.contains("unpasteable")).toBe(true);
  expect(row.getAttribute("aria-label")).toContain("not pasteable");
  // The process row is not part of the tree of objects: it stays as it is.
  expect(doc.querySelector('[data-node-id="process:42"]')?.classList.contains("unpasteable")).toBe(false);
  send({ type: "state", showTemplateParts: false });
  expect(row.classList.contains("unpasteable")).toBe(false);
});

it("copies the label chain and a from_label snippet of the selected object", () => {
  const { doc, posts, send } = spyDom("properties-view");
  const win = windowRow("w1", "MainView", "MainWindow", 'Say "hi"');
  const button = wpfNode("save", "Button", "it's", 2, "", false);
  send({ type: "state", basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES] });
  send({ type: "roots", nodes: [win] });
  send({ type: "children", nodeId: "w1", nodes: [wpfNode("root", "MainView", 'Say "hi"', 1, "MainWindow")], expanded: true });
  send({ type: "children", nodeId: "root", nodes: [button, wpfNode("other", "Button", "it's", 1, "", false)], expanded: true });
  send({ type: "selected", nodeId: "save", properties: { source: "wpf", info: button.info, properties: { ClrFullClassName: "System.Windows.Controls.Button" }, uiaMapped: false } });
  (doc.querySelector("#sidebar-mode") as HTMLInputElement).click();
  const chain = 'Process("App.exe").WPFObject("HwndSource: MainWindow", "Say \\"hi\\"").WPFObject("MainWindow").WPFObject("Button", "it\'s", 2)';
  expect(doc.querySelector('[data-name="FullName"] td')?.textContent).toBe(chain);
  expect(doc.querySelector('[data-name="Name"] td')?.textContent).toBe('WPFObject("Button", "it\'s", 2)');
  expect(doc.querySelector('[data-name="Parent"] td')?.textContent).toBe('WPFObject("MainWindow")');
  const chainItem = doc.querySelector<HTMLButtonElement>("#sidebar-copy-chain")!, codeItem = doc.querySelector<HTMLButtonElement>("#sidebar-copy-code")!;
  expect([chainItem.disabled, codeItem.disabled]).toEqual([false, false]);
  chainItem.click();
  codeItem.click();
  expect(posts).toContainEqual({ type: "copy", text: chain });
  // The snippet is a Python literal that reads back as the same chain.
  expect(posts).toContainEqual({ type: "copy", text: "from_label(app, '" + chain.replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "')" });
  // With template parts shown the same label cannot be pasted: nothing is offered.
  send({ type: "state", showTemplateParts: true });
  send({ type: "selected", nodeId: "save", properties: { source: "wpf", info: button.info, properties: { ClrFullClassName: "System.Windows.Controls.Button" }, uiaMapped: false } });
  expect([chainItem.disabled, codeItem.disabled]).toEqual([true, true]);
  expect(doc.querySelector('[data-name="FullName"] td')?.textContent).toBe(chain);
});

it("offers no copy actions for UI Automation objects", () => {
  const { doc, send } = spyDom("properties-view");
  const uia = { nodeId: "u", source: "uia", hasChildren: false, info: { controlType: "Button", name: "Save", processId: 42, processName: "App.exe" } };
  send({ type: "state", basicProperties: [...DEFAULT_BASIC_PROPERTIES], basicDefaults: [...DEFAULT_BASIC_PROPERTIES] });
  send({ type: "roots", nodes: [{ nodeId: "w", source: "uia", hasChildren: true, info: { controlType: "Window", name: "App", className: "C", processId: 42, processName: "App.exe" } }] });
  send({ type: "children", nodeId: "w", nodes: [uia], expanded: true });
  send({ type: "selected", nodeId: "u", properties: { source: "uia", info: uia.info, properties: {}, inspection: [] } });
  expect(doc.querySelector<HTMLButtonElement>("#sidebar-copy-chain")!.disabled).toBe(true);
  expect(doc.querySelector<HTMLButtonElement>("#sidebar-copy-code")!.disabled).toBe(true);
});
