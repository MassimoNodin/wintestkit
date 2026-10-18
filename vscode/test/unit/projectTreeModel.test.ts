import * as path from "node:path";
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
  it("lists each flow as its own row with the file it lives in", () => {
    const result = discovery();
    const [flow] = buildProjectTree([result]);
    expect(flow).toMatchObject({
      label: "open_page",
      kind: "flow",
      description: path.relative("/project", "/project/flows/navigation.py"),
      icon: "run-all",
      file: result.flows![0].file,
      range,
      children: [],
    });
    expect(result.flows).toHaveLength(1);
  });
  it("keeps multi-project flow identities distinct and skips empty roots", () => {
    const tree = buildProjectTree([discovery(), discovery("/other")]);
    expect(tree.map((node) => node.kind)).toEqual(["project", "project"]);
    expect(tree[0].children[0].id).not.toBe(tree[1].children[0].id);
    expect(tree[0].children[0].kind).toBe("flow");
  });
  it("supports backends without flow discovery and empty workspaces", () => {
    const result = discovery();
    delete result.flows;
    expect(buildProjectTree([result])).toEqual([]);
    expect(buildProjectTree([])).toEqual([]);
  });
  it("orders files by name and keeps each file's flows in discovery order", () => {
    const result = discovery();
    const first = result.flows![0];
    result.flows!.push(
      {
        ...first,
        id: "flows/accounts.py::login",
        file: "/project/flows/accounts.py",
        name: "login",
      },
      { ...first, id: "flows/navigation.py::tour", name: "tour" },
    );
    expect(buildProjectTree([result]).map((node) => node.label)).toEqual([
      "login",
      "open_page",
      "tour",
    ]);
    expect(result.flows![0].name).toBe("open_page");
  });
  it("shows nested paths and files outside the section directory", () => {
    const result = discovery();
    result.flows = [
      { ...result.flows![0], file: "/project/flows/nested/steps.py" },
      {
        ...result.flows![0],
        id: "other::run",
        file: "/project/other/steps.py",
      },
    ];
    expect(buildProjectTree([result]).map((flow) => flow.description)).toEqual([
      path.relative("/project", "/project/flows/nested/steps.py"),
      path.relative("/project", "/project/other/steps.py"),
    ]);
  });
});
