import { describe, expect, it } from "vitest";
import { buildProjectTree } from "../../src/views/projectTreeModel";
import type { DiscoveryResult } from "../../src/protocol/generated";

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

describe("project sidebar sections", () => {
  it("groups flows by source file and navigates to the function name", () => {
    const result = discovery();
    const [file] = buildProjectTree([result]);
    expect(file.label).toBe("navigation.py");
    expect(file.kind).toBe("file");
    expect(file.children[0]).toMatchObject({
      label: "open_page",
      kind: "flow",
      file: result.flows![0].file,
      range,
    });
    expect(result.flows).toHaveLength(1);
  });
  it("keeps multi-project flow identities distinct and skips empty roots", () => {
    const tree = buildProjectTree([discovery(), discovery("/other")]);
    expect(tree.map((node) => node.kind)).toEqual(["project", "project"]);
    expect(tree[0].children[0].children[0].id).not.toBe(
      tree[1].children[0].children[0].id,
    );
  });
  it("supports backends without flow discovery and empty workspaces", () => {
    const result = discovery();
    delete result.flows;
    expect(buildProjectTree([result])).toEqual([]);
    expect(buildProjectTree([])).toEqual([]);
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
      buildProjectTree([result]).map((node) => node.label),
    ).toEqual(["accounts.py", "navigation.py"]);
    expect(result.flows![0].name).toBe("open_page");
  });
  it("preserves nested paths and files outside the section directory", () => {
    const result = discovery();
    result.flows = [
      { ...result.flows![0], file: "/project/flows/nested/steps.py" },
      { ...result.flows![0], id: "other::run", file: "/project/other/steps.py" },
    ];
    const files = buildProjectTree([result]);
    expect(files.map((file) => file.label)).toEqual([
      "nested/steps.py",
      "other/steps.py",
    ]);
  });
});
