import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { buildLenses, describeLocator } from "../../src/editor/lensModel";
import { formatDiagnostic } from "../../src/editor/diagnostics";
import type { ActionFeedback, ActionStatus } from "../../src/editor/lensModel";
import type {
  DiscoveryResult,
  LocatorData,
  Range,
} from "../../src/protocol/generated";

const cases = JSON.parse(
  readFileSync("../python/tests/contract/fixtures/describe_cases.json", "utf8"),
) as { locator: LocatorData; describe: string }[];
const range = (line: number): Range => ({
  start: { line, character: 0 },
  end: { line: line + 1, character: 5 },
});
describe("editor lens model", () => {
  const discovery = JSON.parse(
    readFileSync("../python/tests/contract/fixtures/discovery.json", "utf8"),
  ) as DiscoveryResult;
  const page = discovery.pages[0];
  const element = page.elements.find((element) => element.kind !== "window")!;
  it.each([
    ["running", "Highlighting…", "Checking…"],
    ["found", "Highlighted", "Check: Found"],
    ["not_found", "Highlight: Not found", "Check: Not found"],
    ["ambiguous", "Highlight: Multiple matches", "Check: Multiple matches"],
    ["error", "Highlight: Failed", "Check: Failed"],
  ] as const)(
    "shows %s feedback and preserves retry actions",
    (status, highlight, check) => {
      const result: ActionStatus =
        status === "running"
          ? { status }
          : { status, durationMs: 1, message: "Details" };
      const feedback = new Map<string, ActionFeedback>([
        [element.id, { highlight: result, check: result }],
      ]);
      const lenses = buildLenses(discovery, page.file, new Map(), feedback);
      for (const [command, label] of [
        ["highlightElement", highlight],
        ["checkElement", check],
      ]) {
        const lens = lenses.find(
          (lens) =>
            lens.command === "wintestkit." + command &&
            (lens.args[0] as { qualname?: string }).qualname ===
              element.qualname,
        )!;
        expect(lens.title).toContain(label);
        expect(lens.title).toMatch(/^\$\([^)]+\)\u00a0\u00a0\S/);
        expect(lens.args).toEqual([
          { file: page.file, qualname: element.qualname },
        ]);
        if (status !== "running") expect(lens.tooltip).toBe("Details");
      }
    },
  );
  it("keeps highlight and check feedback independent", () => {
    const lenses = buildLenses(
      discovery,
      page.file,
      new Map(),
      new Map([
        [element.id, { highlight: { status: "found", durationMs: 1 } }],
      ]),
    );
    expect(
      lenses.find(
        (lens) =>
          lens.line === element.range.start.line &&
          lens.command === "wintestkit.checkElement",
      )?.title,
    ).toBe("$(check)\u00a0\u00a0Check");
  });
  it.each(cases)("matches the Python locator format: $describe", (fixture) => {
    expect(describeLocator(fixture.locator)).toBe(fixture.describe);
  });
  it("renders all entry types including dynamic elements and decorated tests", () => {
    const result: DiscoveryResult = {
      version: 1,
      root: "C:/demo",
      errors: [],
      pages: [
        {
          id: "Main",
          file: "C:/demo/page.py",
          name: "Main",
          qualname: "Main",
          bases: ["Page"],
          range: range(1),
          nameRange: range(1),
          elements: [
            {
              id: "window",
              name: "window",
              qualname: "Main.window",
              kind: "window",
              range: range(2),
              nameRange: range(2),
              locator: { window: { title: "Demo" } },
              dynamic: false,
            },
            {
              id: "button",
              name: "button",
              qualname: "Main.button",
              kind: "element",
              range: range(3),
              nameRange: range(3),
              locator: { name: "Go" },
              dynamic: true,
            },
            {
              id: "items",
              name: "items",
              qualname: "Main.items",
              kind: "elements",
              range: range(4),
              nameRange: range(4),
              locator: {},
              dynamic: false,
            },
          ],
        },
      ],
      tests: [
        {
          id: "test",
          file: "C:/demo/page.py",
          name: "test",
          kind: "function",
          parent: null,
          range: range(8),
          nameRange: range(9),
        },
        {
          id: "class",
          file: "C:/demo/page.py",
          name: "TestClass",
          kind: "class",
          parent: null,
          range: range(10),
          nameRange: range(10),
        },
      ],
    };
    const lenses = buildLenses(
      result,
      "C:/demo/page.py",
      new Map([["test", "passed"]]),
    );
    expect(lenses).toHaveLength(11);
    expect(lenses.filter((lens) => lens.line === 2)).toHaveLength(1);
    expect(
      lenses.find((lens) => lens.title === "$(pass-filled)\u00a0\u00a0Passed")
        ?.command,
    ).toBe("");
    expect(
      lenses.find((lens) => lens.command === "wintestkit.runTest")?.line,
    ).toBe(8);
    expect(
      lenses.find((lens) => lens.title === "$(play)\u00a0\u00a0Run tests"),
    ).toBeDefined();
    expect(buildLenses(result, "C:/elsewhere.py", new Map())).toEqual([]);
  });
  it("formats detailed diagnostics without losing candidate mismatches", () => {
    const text = formatDiagnostic({
      kind: "not_found",
      message: "Missing",
      locator: "Button",
      searchedIn: "Demo",
      matchCount: 0,
      candidates: [
        {
          info: {
            controlType: "Button",
            name: "Go",
            automationId: "",
            className: "Button",
            frameworkId: "WPF",
            processId: 1,
            isEnabled: true,
            isOffscreen: false,
            hasKeyboardFocus: false,
            rect: { left: 1, top: 2, width: 3, height: 4 },
            runtimeId: "1",
          },
          score: 1,
          mismatches: [{ property: "name", expected: "Stop", actual: "Go" }],
        },
      ],
    });
    expect(text).toContain('1. Button "Go" [class=Button] at (1,2 3x4)');
    expect(text).toContain("name: expected Stop, got Go");
    expect(text.split("\n")).toHaveLength(5);
  });
});
