import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { JSDOM } from "jsdom";
import { expect, it } from "vitest";
const { labelsFor, iconFor, kind, pasteable, processLabel, copyAsCode, pythonString } = createRequire(import.meta.url)("../../media/spy/treeLabels.js");
const w = (name: string, xName = "") => ({ source: "wpf", info: { controlType: "ListBoxItem", name }, identity: { type: "Controls.ListBoxItem", xName }, wpfText: name });
const u = (name: string, id = "") => ({ source: "uia", info: { controlType: "Button", name, automationId: id } });
it("minimizes labels across pages and escapes arguments", () => {
  expect(labelsFor([w("Alpha", "item")])).toEqual(['WPFObject("item")']);
  // The index is wpf:Ordinal: the place among the siblings of the same type, whatever their texts.
  expect(labelsFor([w("Alpha"), w("Beta"), w("Beta"), w("Gamma")])).toEqual(['WPFObject("ListBoxItem", "Alpha")', 'WPFObject("ListBoxItem", "Beta", 2)', 'WPFObject("ListBoxItem", "Beta", 3)', 'WPFObject("ListBoxItem", "Gamma")']);
  expect(labelsFor([w(""), w("")])).toEqual(['WPFObject("ListBoxItem", 1)', 'WPFObject("ListBoxItem", 2)']);
  expect(labelsFor([w('\u96ea "a"')])[0]).toBe('WPFObject("ListBoxItem", "\u96ea \\"a\\"")');
  expect(labelsFor([u(""), u("")])).toEqual(['UIAObject("Button", "", 1)', 'UIAObject("Button", "", 2)']);
  expect(labelsFor([u("A")])).toEqual(['UIAObject("Button")']);
  expect(labelsFor([u("A"), u("A")])).toEqual(['UIAObject("Button", "A", 1)', 'UIAObject("Button", "A", 2)']);
  expect(labelsFor([u("A", "id"), u("B")])[0]).toBe('UIAObject("id")');
  const win = (name: string) => ({ source: "uia", info: { controlType: "Window", className: "C", name } });
  expect(labelsFor([win("A")])).toEqual(['Window("C")']);
  expect(labelsFor([win("A"), win("B")])).toEqual(['Window("C", "A")', 'Window("C", "B")']);
  expect(labelsFor([win("A"), win("A")])).toEqual(['Window("C", "A", 1)', 'Window("C", "A", 2)']);
});
it("labels native window controls by class, then text, then position", () => {
  const native = (className: string, name = "", controlType = "Edit") => ({ source: "uia", info: { controlType, className, name, nativeWindowHandle: 4242, frameworkId: "Win32" } });
  // Only as many arguments as it takes to tell siblings apart, as for WPF objects.
  expect(labelsFor([native("Edit")])).toEqual(['Window("Edit")']);
  expect(labelsFor([native("Edit", "hello")])).toEqual(['Window("Edit")']);
  expect(labelsFor([native("Edit", "a"), native("Button", "OK", "Button")])).toEqual(['Window("Edit")', 'Window("Button")']);
  expect(labelsFor([native("Button", "OK", "Button"), native("Button", "Cancel", "Button")])).toEqual(['Window("Button", "OK")', 'Window("Button", "Cancel")']);
  expect(labelsFor([native("Edit"), native("Edit")])).toEqual(['Window("Edit", "", 1)', 'Window("Edit", "", 2)']);
  expect(labelsFor([native("Edit", "x"), native("Edit", "x"), native("Edit", "y")])).toEqual(['Window("Edit", "x", 1)', 'Window("Edit", "x", 2)', 'Window("Edit", "y")']);
  // A top-level window and a control with a handle are the same kind of object.
  const top = { source: "uia", info: { controlType: "Window", className: "#32770", name: "Open", nativeWindowHandle: 1 } };
  expect(labelsFor([top, native("Edit")])).toEqual(['Window("#32770")', 'Window("Edit")']);
  expect(labelsFor([native('Say "hi"', "雪")])).toEqual(['Window("Say \\"hi\\"")']);
});
it("leaves UIA and WPF objects without a native window handle as they were", () => {
  const plain = (controlType: string, name: string, extra: Record<string, unknown> = {}) => ({ source: "uia", info: { controlType, className: "Edit", name, ...extra } });
  // No handle (or an empty one): still UIAObject, whatever the class says.
  expect(labelsFor([plain("Edit", "a")])).toEqual(['UIAObject("Edit")']);
  expect(labelsFor([plain("Edit", "a", { nativeWindowHandle: 0 })])).toEqual(['UIAObject("Edit")']);
  expect(labelsFor([plain("Edit", "a", { nativeWindowHandle: 5, className: "" })])).toEqual(['UIAObject("Edit")']);
  // A WPF object keeps its WPF label even when UI Automation reports a handle for it.
  const wpf = { source: "wpf", info: { controlType: "TextBox", name: "", className: "TextBox", nativeWindowHandle: 7 }, identity: { type: "System.Windows.Controls.TextBox", xName: "input" } };
  expect(labelsFor([wpf])).toEqual(['WPFObject("input")']);
  // Siblings of different kinds do not count each other when numbering.
  const native = { source: "uia", info: { controlType: "Edit", className: "Edit", name: "", nativeWindowHandle: 9 } };
  expect(labelsFor([plain("Edit", ""), native, plain("Edit", "")])).toEqual(['UIAObject("Edit", "", 1)', 'Window("Edit")', 'UIAObject("Edit", "", 2)']);
});
it("maps every UIA type and WPF panels", () => {
  const types = readFileSync("../python/src/wintestkit/uia/constants.py", "utf8").split("_CONTROL_TYPE_NAMES_IN_ORDER = (")[1].split(")")[0].match(/"[A-Za-z]+"/g)!.map((x) => JSON.parse(x));
  for (const type of [...types, "ListBox", "ListBoxItem", "TextBox", "TextBlock", "Border", "StackPanel", "Grid", "DockPanel", "Canvas", "ContentPresenter", "ScrollViewer"]) expect(iconFor(type), type).not.toBe("symbol-object");
  expect(iconFor("unknown")).toBe("symbol-object");
});
it("shows mixed labels, badges, and General Name", () => {
  const dom = new JSDOM(readFileSync("media/spy/spy.html", "utf8").replace("{{viewClass}}", "properties-view"), { runScripts: "outside-only" });
  Object.assign(dom.window, { acquireVsCodeApi: () => ({ postMessage() {} }), matchMedia: () => ({ matches: false, addEventListener() {} }), requestAnimationFrame: (fn: () => void) => fn() });
  dom.window.eval(readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));
  const send = (data: unknown) => dom.window.dispatchEvent(new dom.window.MessageEvent("message", { data }));
  const root = { ...u("Root"), nodeId: "root", hasChildren: true };
  const child = { ...w("Alpha", "item"), nodeId: "child", hasChildren: false };
  send({ type: "roots", nodes: [root] });
  send({ type: "children", nodeId: "root", nodes: [child, { ...u("Search"), nodeId: "other", hasChildren: false }] });
  const row = dom.window.document.querySelector('[data-node-id="child"]')!;
  expect(row.getAttribute("aria-label")).toBe('WPFObject("item")');
  expect(row.textContent).toContain('WPFObject("item")');
  expect(row.querySelector(".technology-badge")?.getAttribute("aria-label")).toBe("WPF object");
  expect(dom.window.document.querySelector('[data-node-id="other"] .technology-badge')?.textContent).toBe("UIA");
  send({ type: "children", nodeId: "root", append: true, nodes: [{ ...w("Beta", "item"), nodeId: "third", hasChildren: false }] });
  expect(row.getAttribute("aria-label")).toBe('WPFObject("ListBoxItem", "Alpha")');
  send({ type: "selected", nodeId: "child", properties: { source: "wpf", info: child.info, properties: {} } });
  expect(dom.window.document.querySelector("#properties tr:first-child td")?.textContent).toBe('WPFObject("ListBoxItem", "Alpha")');
  dom.window.close();
});
const f = (name: string, xName = "", type = "System.Windows.Forms.Button") => ({ source: "winforms", info: { controlType: type.split(".").pop(), name }, identity: { type, xName } });
it("labels WinForms controls by their Name, then by type, text and place among siblings", () => {
  expect(labelsFor([f("OK", "button1")])).toEqual(['WinFormsObject("button1")']);
  expect(labelsFor([f("OK", "button1"), f("Cancel", "button2")])).toEqual(['WinFormsObject("button1")', 'WinFormsObject("button2")']);
  // Only as many arguments as it takes, like WPFObject: the type, the text when there is one, then the ordinal.
  expect(labelsFor([f("OK"), f("Cancel")])).toEqual(['WinFormsObject("Button", "OK")', 'WinFormsObject("Button", "Cancel")']);
  expect(labelsFor([f("OK"), f("OK"), f("Other", "", "System.Windows.Forms.Label")])).toEqual(['WinFormsObject("Button", "OK", 1)', 'WinFormsObject("Button", "OK", 2)', 'WinFormsObject("Label", "Other")']);
  expect(labelsFor([f(""), f("")])).toEqual(['WinFormsObject("Button", 1)', 'WinFormsObject("Button", 2)']);
  // A name shared by two siblings cannot tell them apart, so they fall back to the type and text.
  expect(labelsFor([f("A", "same"), f("B", "same")])).toEqual(['WinFormsObject("Button", "A")', 'WinFormsObject("Button", "B")']);
  expect(labelsFor([f('say "hi"', "named"), f("x", "")])[0]).toBe('WinFormsObject("named")');
  // WinForms and WPF objects are counted apart.
  expect(labelsFor([f("OK"), w("OK")])).toEqual(['WinFormsObject("Button", "OK")', 'WPFObject("ListBoxItem", "OK")']);
  // A form with a Name reads like its other controls; an unnamed form keeps the window label.
  expect(labelsFor([{ source: "winforms", info: { controlType: "Window", className: "WindowsForms10.Window.8.app.0.1", name: "Main", automationId: "mainForm" } }])).toEqual(['WinFormsObject("mainForm")']);
  expect(labelsFor([{ source: "winforms", info: { controlType: "Window", className: "WindowsForms10.Window.8.app.0.1", name: "Main" } }])).toEqual(['Window("WindowsForms10.Window.8.app.0.1")']);
});
it("has WinForms badges and icons", () => {
  const { badgeFor } = createRequire(import.meta.url)("../../media/spy/treeLabels.js");
  expect(badgeFor(f("OK", "button1"), false)).toBe("WinForms");
  expect(badgeFor({ source: "uia", info: { controlType: "Window", frameworkId: "WinForm", className: "WindowsForms10.Window.8.app.0.1" } }, true)).toBe("WinForms");
  expect(badgeFor(w("A"), false)).toBe("WPF");
  expect(badgeFor(u("A"), false)).toBe("UIA");
  for (const type of ["Form", "Label", "GroupBox", "TabControl", "TabPage", "DataGridView", "MenuStrip", "ToolStripMenuItem", "Panel", "UserControl", "ListView", "TreeView"]) expect(iconFor(type), type).not.toBe("symbol-object");
});

// -- the label grammar shared with python/src/wintestkit/labels.py ---------------------------------------------
interface ConformanceCase { name: string; kind: "objects" | "windows" | "windowNodes"; nodes: Record<string, string | null>[]; labels: string[] }
const conformance: ConformanceCase[] = JSON.parse(readFileSync("../python/tests/fixtures/label_conformance.json", "utf8")).cases;
// The siblings as the Spy receives them: wpf:Text and wpf:Ordinal come from the agent, never from the other siblings.
const nodesOf = (item: ConformanceCase) => {
  const seen = new Map<string, number>();
  return item.nodes.map((node) => {
    if (item.kind === "windows") return { source: "uia", info: { controlType: "Window", className: node.class, name: node.caption } };
    if (item.kind === "windowNodes") return { source: "wpf", windowNode: true, info: { controlType: "Window", className: "HwndWrapper[App;;1]", name: "" }, identity: { type: "Fixture." + node.rootType, xName: node.rootName }, ...(node.text === null ? {} : { wpfText: node.text }) };
    seen.set(node.type!, (seen.get(node.type!) ?? 0) + 1);
    return { source: "wpf", info: { controlType: node.type, name: "" }, identity: { type: "Fixture." + node.type, xName: node.name }, wpfOrdinal: seen.get(node.type!), ...(node.text === null ? {} : { wpfText: node.text }) };
  });
};
it.each(conformance.map((item) => [item.name, item] as const))("conformance: %s", (_name, item) => {
  expect(labelsFor(nodesOf(item))).toEqual(item.labels);
});
it("takes the ordinal from the agent, not from the siblings that happen to be loaded", () => {
  // Only the second page of a long list is loaded: its ordinals still count the first page.
  const page = [{ ...w("Beta"), wpfOrdinal: 51 }, { ...w("Beta"), wpfOrdinal: 52 }];
  expect(labelsFor(page)).toEqual(['WPFObject("ListBoxItem", "Beta", 51)', 'WPFObject("ListBoxItem", "Beta", 52)']);
});
it("knows which labels the Python library can read back", () => {
  const [window, object, native, uia, forms] = [nodesOf({ name: "", labels: [], kind: "windowNodes", nodes: [{ rootType: "V", rootName: "", text: "" }] })[0], w("a"), { source: "uia", info: { controlType: "Window", className: "C", name: "x" } }, u("a"), f("a")];
  expect([window, object, native].map(pasteable)).toEqual([true, true, true]);
  expect([uia, forms].map(pasteable)).toEqual([false, false]);
  expect(kind(window)).toBe("WindowNode");
  // A WPF window row whose root visual is not described yet keeps its Win32 label.
  expect(labelsFor([{ source: "wpf", info: { controlType: "Window", className: "HwndWrapper[App;;1]", name: "Main" } }])).toEqual(['Window("HwndWrapper[App;;1]")']);
  // The root visual of a window is an object, even when its type is Window.
  expect(labelsFor([{ source: "wpf", info: { controlType: "Window", name: "Main" }, identity: { type: "System.Windows.Window", xName: "" }, wpfText: "Main", wpfOrdinal: 1 }])).toEqual(['WPFObject("Window", "Main")']);
});
it("writes the process and a Python snippet that reads the chain back", () => {
  expect(processLabel("app.exe")).toBe('Process("app.exe")');
  const chain = 'Process("app.exe").WPFObject("HwndSource: Main", "say \\"hi\\"").Window("C:\\x")';
  expect(copyAsCode(chain)).toBe("from_label(app, '" + chain.replace(/\\/g, "\\\\") + "')");
  expect(pythonString("it's\n")).toBe("'it\\'s\\n'");
});
