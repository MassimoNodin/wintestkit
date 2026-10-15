import { describe, expect, it } from "vitest";
import { buildProjectTree } from "../../src/views/projectTreeModel";
import type { DiscoveryResult, TestEntry } from "../../src/protocol/generated";

const range = {
  start: { line: 1, character: 4 },
  end: { line: 1, character: 12 },
};
const discovery = (root = "/project"): DiscoveryResult => ({
  version: 1,
  root,
  pages: [],
  tests: [],
  errors: [],
  flows: [
    {
      id: "flows/navigation.py::open_page",
      name: "open_page",
      file: root + "/flows/navigation.py",
      range,
      nameRange: range,
    },
  ],
});
const testEntry = (
  name: string,
  kind: TestEntry["kind"] = "function",
  parent: string | null = null,
): TestEntry => ({
  id: "tests/test_app.py::" + (parent ? "TestApp::" : "") + name,
  file: "/project/tests/test_app.py",
  name,
  kind,
  parent,
  range,
  nameRange: range,
});

describe("project sidebar sections", () => {
  it("groups flows by source file and navigates to the function name", () => {
    const result = discovery();
    const [file] = buildProjectTree([result], "flows");
    expect(file.label).toBe("navigation.py");
    expect(file.kind).toBe("file");
    expect(file.children[0]).toMatchObject({
      label: "open_page",
      kind: "flow",
      file: result.flows![0].file,
      range,
      testId: undefined,
    });
    expect(result.flows).toHaveLength(1);
  });
  it("groups tests by file and class, preserving pytest targets", () => {
    const result = discovery();
    const parent = testEntry("TestApp", "class");
    const child = testEntry("test_open", "function", parent.id);
    result.tests = [child, parent, testEntry("test_standalone")];
    const [file] = buildProjectTree([result], "tests");
    expect(file.label).toBe("test_app.py");
    expect(file.id).toBe("tests|/project|tests/test_app.py");
    expect(file.testId).toBe("tests/test_app.py");
    expect(file.children.map((node) => node.label)).toEqual([
      "TestApp",
      "test_standalone",
    ]);
    expect(file.children[0].children[0]).toMatchObject({
      label: "test_open",
      kind: "test",
      testId: child.id,
      root: "/project",
    });
    expect(file.children[0].kind).toBe("test-class");
  });
  it("keeps multi-project flow identities distinct and skips empty roots", () => {
    const tree = buildProjectTree([discovery(), discovery("/other")], "flows");
    expect(tree.map((node) => node.kind)).toEqual(["project", "project"]);
    expect(tree[0].children[0].children[0].id).not.toBe(
      tree[1].children[0].children[0].id,
    );
    expect(
      buildProjectTree([discovery(), discovery("/other")], "tests"),
    ).toEqual([]);
  });
  it("supports backends without flow discovery and empty workspaces", () => {
    const result = discovery();
    delete result.flows;
    expect(buildProjectTree([result], "flows")).toEqual([]);
    expect(buildProjectTree([], "tests")).toEqual([]);
  });
  it("sorts source files without changing discovery order", () => {
    const result = discovery();
    result.flows!.push({
      ...result.flows![0],
      id: "flows/accounts.py::login",
      file: "/project/flows/accounts.py",
      name: "login",
    });
    expect(
      buildProjectTree([result], "flows").map((node) => node.label),
    ).toEqual(["accounts.py", "navigation.py"]);
    expect(result.flows![0].name).toBe("open_page");
  });
  it("preserves nested paths and files outside the section directory", () => {
    const result = discovery();
    result.tests = [
      { ...testEntry("test_nested"), file: "/project/tests/nested/test_app.py" },
      { ...testEntry("test_other"), file: "/project/other/test_app.py" },
    ];
    const files = buildProjectTree([result], "tests");
    expect(files.map((file) => file.label)).toEqual([
      "nested/test_app.py",
      "other/test_app.py",
    ]);
    expect(files[0].testId).toBe("tests/nested/test_app.py");
  });
});
