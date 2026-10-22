import { describe, expect, it } from "vitest";
import type { NodeInfo } from "../../src/protocol/generated";
import {
  bestMatch,
  describeSegment,
  MAX_PATH_DEPTH,
  parseSelectionPath,
  segmentOf,
  type PathSegment,
} from "../../src/spy/selectionPath";

const node = (
  nodeId: string,
  controlType: string,
  extra: { name?: string; automationId?: string; className?: string } = {},
): NodeInfo =>
  ({
    nodeId,
    hasChildren: false,
    info: { controlType, name: "", automationId: "", className: "", ...extra },
  }) as unknown as NodeInfo;
const segment = (value: Partial<PathSegment> & { controlType: string }): PathSegment => ({
  automationId: "", name: "", className: "", ...value,
});

describe("selection path validation", () => {
  const good = { controlType: "Pane", automationId: "", name: "Editor", className: "P", index: 2 };
  it("accepts a well-formed path", () => {
    expect(parseSelectionPath([good, { ...good, index: undefined }])).toEqual([good, { controlType: "Pane", automationId: "", name: "Editor", className: "P" }]);
  });
  it.each([
    undefined, null, "path", {}, [], [null], ["x"], [{ ...good, controlType: 5 }], [{ ...good, name: undefined }],
    [{ ...good, className: "x".repeat(513) }], [{ ...good, index: -1 }], [{ ...good, index: 1.5 }], [{ ...good, index: "1" }],
    Array.from({ length: MAX_PATH_DEPTH + 1 }, () => good),
  ])("rejects a malformed path %#", (value) => {
    expect(parseSelectionPath(value)).toBeUndefined();
  });
  it("keeps only the known fields", () => {
    expect(parseSelectionPath([{ ...good, extra: "ignored", __proto__: { x: 1 } }])).toEqual([good]);
  });
});

describe("describing and building segments", () => {
  it("describes an object the way the user knows it", () => {
    expect(describeSegment(segment({ controlType: "Pane", name: "Editor" }))).toBe('Pane "Editor"');
    expect(describeSegment(segment({ controlType: "Button", automationId: "Save" }))).toBe("Button #Save");
    expect(describeSegment(segment({ controlType: "Pane", className: "Panel" }))).toBe("Pane [Panel]");
    expect(describeSegment(segment({ controlType: "Pane" }))).toBe("Pane");
    expect(describeSegment(segment({ controlType: "Edit", name: "x".repeat(100) }))).toHaveLength('Edit "'.length + 57 + 4);
  });
  it("takes a segment from node info, with the position when known", () => {
    const info = node("n", "Button", { name: "Save", automationId: "id", className: "B" }).info;
    expect(segmentOf(info, 3)).toEqual({ controlType: "Button", automationId: "id", name: "Save", className: "B", index: 3 });
    expect(segmentOf(info)).not.toHaveProperty("index");
  });
});

describe("finding the same object again", () => {
  it("prefers an exact match over a look-alike", () => {
    const wanted = segment({ controlType: "Button", name: "Save", automationId: "save", className: "B" });
    const found = bestMatch(wanted, [node("a", "Button", { name: "Cancel", className: "B" }), node("b", "Button", { name: "Save", automationId: "save", className: "B" })]);
    expect(found?.nodeId).toBe("b");
  });
  it("trusts an automation id even when the name changed", () => {
    const wanted = segment({ controlType: "Button", name: "Save", automationId: "save", className: "B" });
    expect(bestMatch(wanted, [node("a", "Button", { name: "Save as...", automationId: "save", className: "B" })])?.nodeId).toBe("a");
  });
  it("follows a window whose title gained or lost a file name", () => {
    const wanted = segment({ controlType: "Window", name: "wintestkit - Visual Studio Code", className: "Chrome_WidgetWin_1" });
    const roots = [
      node("t3", "Window", { name: "T3 Code (Beta)", className: "Chrome_WidgetWin_1" }),
      node("vs", "Window", { name: "main.py - wintestkit - Visual Studio Code", className: "Chrome_WidgetWin_1" }),
    ];
    expect(bestMatch(wanted, roots)?.nodeId).toBe("vs");
  });
  it("never picks one of several look-alikes without something to tell them apart", () => {
    const wanted = segment({ controlType: "Window", name: "Visual Studio Code", className: "Chrome_WidgetWin_1" });
    const roots = [
      node("one", "Window", { name: "a - Visual Studio Code", className: "Chrome_WidgetWin_1" }),
      node("two", "Window", { name: "b - Visual Studio Code", className: "Chrome_WidgetWin_1" }),
    ];
    expect(bestMatch(wanted, roots)).toBeUndefined();
  });
  it("uses the position among siblings to tell identical objects apart", () => {
    const panes = [0, 1, 2].map((i) => node("p" + i, "Pane", { className: "Panel" }));
    expect(bestMatch(segment({ controlType: "Pane", className: "Panel", index: 1 }), panes)?.nodeId).toBe("p1");
    expect(bestMatch(segment({ controlType: "Pane", className: "Panel" }), panes)).toBeUndefined();
  });
  it("lets a weak match through only when the position confirms it", () => {
    const wanted = segment({ controlType: "Group", className: "Old", index: 1 });
    const siblings = [node("a", "Text"), node("b", "Group", { className: "New" })];
    expect(bestMatch(wanted, siblings)?.nodeId).toBe("b"); // a Group still sits where it was
    expect(bestMatch({ ...wanted, index: 0 }, siblings)).toBeUndefined();
  });
  it("does not accept a different control type or an empty list", () => {
    const wanted = segment({ controlType: "Button", name: "Save", className: "B" });
    expect(bestMatch(wanted, [node("a", "Edit", { name: "Save", className: "B" })])).toBeUndefined();
    expect(bestMatch(wanted, [])).toBeUndefined();
  });
  it("reports a deleted object as not found even when others of its kind remain", () => {
    const wanted = segment({ controlType: "Button", name: "Save", automationId: "save", className: "B", index: 4 });
    const open = node("a", "Button", { name: "Open", automationId: "open", className: "B" });
    const close = node("b", "Button", { name: "Close", automationId: "close", className: "B" });
    expect(bestMatch(wanted, [open])).toBeUndefined(); // one look-alike is still not it
    expect(bestMatch(wanted, [open, close])).toBeUndefined();
  });
  it("accepts a renamed object only where it used to be", () => {
    const wanted = segment({ controlType: "Text", name: "Ready", className: "T", index: 2 });
    const others = [node("a", "Text", { name: "x", className: "T" }), node("b", "Text", { name: "y", className: "T" })];
    expect(bestMatch(wanted, [...others, node("c", "Text", { name: "Busy", className: "T" })])?.nodeId).toBe("c");
    expect(bestMatch({ ...wanted, index: 7 }, [...others, node("c", "Text", { name: "Busy", className: "T" })])).toBeUndefined();
  });
  it("does not treat a short name inside a longer one as the same object", () => {
    const wanted = segment({ controlType: "Text", name: "Ready", className: "T", index: 9 });
    expect(bestMatch(wanted, [node("a", "Text", { name: "y", className: "T" })])).toBeUndefined();
  });
  it("finds an object that lost its name when it still sits where it was", () => {
    const wanted = segment({ controlType: "Group", className: "G", name: "was named", index: 1 });
    expect(bestMatch(wanted, [node("a", "Group", { className: "G" }), node("b", "Group", { className: "G" })])?.nodeId).toBe("b");
    expect(bestMatch({ ...wanted, index: 5 }, [node("a", "Group", { className: "G" }), node("b", "Group", { className: "G" })])).toBeUndefined();
  });
});
