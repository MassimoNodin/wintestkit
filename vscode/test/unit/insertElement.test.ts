import * as path from "node:path";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  computeInsertion,
  validIdentifier,
} from "../../src/spy/insertionModel";
import type {
  ElementEntry,
  PageEntry,
  Suggestion,
} from "../../src/protocol/generated";

const range = (line: number, end = line) => ({
  start: { line, character: 0 },
  end: { line: end, character: 0 },
});
const suggestion: Suggestion = {
  locator: { controlType: "Button", name: "OK" },
  code: 'Element(control_type="Button", name="OK")',
  attributeName: "ok",
  helpers: [],
  unique: true,
  matchCount: 1,
  strategy: "name",
};
const page = (source: string, elements: ElementEntry[] = []): PageEntry => {
  const lines = source.split(/\r?\n/);
  const line = lines.findIndex((line) => line.startsWith("class Main"));
  return {
    id: "Main",
    name: "Main",
    qualname: "Main",
    file: "page.py",
    bases: ["Page"],
    range: range(line, lines.length - 1),
    nameRange: range(line),
    elements,
  };
};
const entry = (name: string, line: number, locator = {}): ElementEntry => ({
  id: name,
  name,
  qualname: "Main." + name,
  kind: name === "window" ? "window" : "element",
  locator,
  dynamic: false,
  range: range(line),
  nameRange: range(line),
});
const insert = (
  source: string,
  selected: PageEntry | null,
  next = suggestion,
  newPage?: { className: string },
): string => {
  const result = computeInsertion(
    source,
    selected,
    newPage,
    next,
    next.attributeName,
  );
  const lines = source.split(/\r?\n/);
  const newline = source.includes("\r\n") ? "\r\n" : "\n";
  const offset = (position: { line: number; character: number }) =>
    lines
      .slice(0, position.line)
      .reduce((total, line) => total + line.length + newline.length, 0) +
    position.character;
  let updated = source;
  for (const edit of [...result.edits].sort(
    (first, second) => offset(second.range.start) - offset(first.range.start),
  ))
    updated =
      updated.slice(0, offset(edit.range.start)) +
      edit.text +
      updated.slice(offset(edit.range.end));
  const parsed = spawnSync(
    existsSync(path.resolve("../python/.venv/Scripts/python.exe"))
      ? path.resolve("../python/.venv/Scripts/python.exe")
      : "python",
    ["-c", "import ast,sys; ast.parse(sys.stdin.read())"],
    { input: updated, encoding: "utf8" },
  );
  expect(parsed.status, parsed.stderr + "\n" + updated).toBe(0);
  return updated;
};
describe("Spy element insertion", () => {
  it("appends after multiline declarations and extends imports", () => {
    const source =
      'from wintestkit import Page, Window\n\nclass Main(Page):\n    window = Window(title="Demo")\n    button = Element(\n        name="Other",\n    )\n\n    def helper(self):\n        return self.button\n';
    const multiline = entry("button", 4);
    multiline.range.end.line = 6;
    const updated = insert(
      source,
      page(source, [entry("window", 3), multiline]),
    );
    expect(updated).toContain("from wintestkit import Page, Window, Element");
    expect(updated).toContain(
      '    )\n    ok = Element(control_type="Button", name="OK")\n\n    def helper',
    );
  });
  it("imports the typed element a suggestion declares", () => {
    const source =
      'from wintestkit import Page, Window\n\nclass Main(Page):\n    window = Window(title="Demo")\n';
    const typed = {
      ...suggestion,
      code: 'ComboBox(automation_id="Country", within=Element(name="Text (1)"))',
      attributeName: "country",
    };
    const updated = insert(source, page(source, [entry("window", 3)]), typed);
    expect(updated).toContain(
      "from wintestkit import Page, Window, Element, ComboBox",
    );
    expect(updated).not.toContain("Text,");
  });
  it("keeps class docstrings and inserts windows before new declarations", () => {
    const source =
      'from wintestkit import Page\n\nclass Main(Page):\n    """A page.\n    More detail.\n    """\n    pass\n';
    const updated = insert(source, page(source), {
      ...suggestion,
      window: { code: 'Window(title="Demo")', locator: { title: "Demo" } },
    });
    expect(updated).toContain(
      '    """\n    window = Window(title="Demo")\n    ok = Element',
    );
  });
  it("reuses equivalent helpers with different locator key order", () => {
    const source =
      'from wintestkit import Page, Element\n\nclass Main(Page):\n    container = Element(name="Panel", control_type="Group")\n';
    const next = {
      ...suggestion,
      code: 'Element(name="OK", within=panel)',
      helpers: [
        {
          attributeName: "panel",
          code: 'Element(control_type="Group", name="Panel")',
          locator: { name: "Panel", controlType: "Group" },
        },
      ],
    };
    const updated = insert(
      source,
      page(source, [
        entry("container", 3, { controlType: "Group", name: "Panel" }),
      ]),
      next,
    );
    expect(updated).toContain('ok = Element(name="OK", within=container)');
    expect(updated).not.toContain("panel =");
  });
  it("renames colliding helper attributes and rewrites within references", () => {
    const source =
      'from wintestkit import Page, Element\n\nclass Main(Page):\n    panel = Element(name="Other")\n';
    const next = {
      ...suggestion,
      code: 'Element(name="OK", within=panel)',
      helpers: [
        {
          attributeName: "panel",
          code: 'Element(name="Panel")',
          locator: { name: "Panel" },
        },
      ],
    };
    const updated = insert(
      source,
      page(source, [entry("panel", 3, { name: "Other" })]),
      next,
    );
    expect(updated).toContain('panel_2 = Element(name="Panel")');
    expect(updated).toContain("within=panel_2");
  });
  it("adds regex imports once and handles parenthesized imports", () => {
    const source =
      "from wintestkit import (\n    Page,\n    Element,\n)\n\nclass Main(Page):\n    pass\n";
    const next = { ...suggestion, code: 'Element(name=re.compile("OK.*"))' };
    const updated = insert(source, page(source), next);
    expect(updated).toContain("import re\n");
    expect(updated.match(/from wintestkit import/g)).toHaveLength(1);
    expect(
      insert(
        updated,
        page(updated, [
          entry(
            "ok",
            updated.split("\n").findIndex((line) => line.includes("ok =")),
          ),
        ]),
        { ...next, attributeName: "other" },
      ).match(/import re/g),
    ).toHaveLength(1);
  });
  it("creates a page in an empty file or appends to an existing module", () => {
    expect(insert("", null, suggestion, { className: "NewPage" })).toContain(
      "class NewPage(Page):",
    );
    const source = '"""Module docs."""\nfrom __future__ import annotations\n';
    const updated = insert(source, null, suggestion, {
      className: "NewPage",
    });
    expect(updated.startsWith(source)).toBe(true);
    expect(updated).toContain("from wintestkit import Page, Element");
  });
  it("preserves module docstrings, tab indentation and CRLF", () => {
    const source = '"""Module docs."""\r\n\r\nclass Main(Page):\r\n\tpass\r\n';
    const updated = insert(source, page(source));
    expect(updated.startsWith('"""Module docs."""\r\n')).toBe(true);
    expect(updated).toContain("\tok = Element");
    expect(updated.replaceAll("\r\n", "")).not.toContain("\n");
  });
  it("rejects keywords, duplicate attributes and stale discovery ranges", () => {
    expect(validIdentifier("class")).toBe(false);
    expect(validIdentifier("has-space")).toBe(false);
    const source = "class Main(Page):\n    pass\n";
    expect(() =>
      computeInsertion(
        source,
        page(source, [entry("ok", 1)]),
        undefined,
        suggestion,
        "ok",
      ),
    ).toThrow("already defined");
    expect(() =>
      computeInsertion(
        source.replace("Main", "Renamed"),
        page(source),
        undefined,
        suggestion,
        "ok",
      ),
    ).toThrow("page changed");
  });
});
