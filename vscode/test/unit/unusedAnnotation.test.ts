import { describe, expect, it } from "vitest";
import type { ElementNode } from "../../src/views/elementsTreeModel";
import { annotateUnused, type UnusedLookup } from "../../src/views/unusedAnnotation";

const node = (id: string, children: ElementNode[] = [], elementId?: string): ElementNode => ({
  id,
  label: id,
  description: "desc",
  kind: elementId ? "element" : "page",
  icon: "symbol-field",
  children,
  elementId,
});
const lookup = (unused: string[], scanned = ["A"]): UnusedLookup => ({
  ownerOf: (item) => (item.id.startsWith("A|") ? "A" : item.id.startsWith("B|") ? "B" : undefined),
  hasResult: (owner) => scanned.includes(owner),
  isUnused: (_owner, id) => unused.includes(id),
});

describe("unused definition annotation", () => {
  const tree = [
    node("A|page", [
      node("A|group", [node("A|child", [], "child")], "group"),
      node("A|used", [], "used"),
    ]),
    node("B|page", [node("B|other", [], "other")]),
  ];
  it("marks unused definitions without changing the rest", () => {
    const result = annotateUnused(tree, lookup(["child"]), false);
    expect(result[0].children[0].children[0].description).toBe("desc · possibly unused");
    expect(result[0].children[0].children[0].tooltip).toContain("static estimate");
    expect(result[0].children[1].description).toBe("desc");
    expect(result[1].children[0].description).toBe("desc");
  });
  it("keeps a used parent when one of its children is unused", () => {
    const result = annotateUnused(tree, lookup(["child"]), true);
    const page = result.find((item) => item.id === "A|page")!;
    expect(page.children.map((item) => item.id)).toEqual(["A|group"]);
    expect(page.children[0].children.map((item) => item.id)).toEqual(["A|child"]);
    expect(page.children[0].description).toBe("desc");
  });
  it("drops pages with nothing unused only for scanned projects", () => {
    const result = annotateUnused(tree, lookup([]), true);
    expect(result.map((item) => item.id)).toEqual(["B|page"]);
    expect(result[0].children).toHaveLength(1);
  });
  it("ignores definitions from projects that were never scanned", () => {
    expect(annotateUnused(tree, lookup(["other"], []), false)[1].children[0].description).toBe("desc");
  });
});
