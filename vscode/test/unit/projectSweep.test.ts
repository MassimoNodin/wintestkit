import { describe, expect, it } from "vitest";
import { classifySweepBindings } from "../../src/editor/projectSweep";
import type { Binding } from "../../src/editor/checkAfterFlow";
import type { FlowEntry, PageEntry } from "../../src/protocol/generated";

describe("project sweep selection", () => {
  it("uses remembered runnable flows and lists unbound or parameterized pages as skipped", () => {
    const pages = [
      { file: "C:/p/a.py", qualname: "A" },
      { file: "C:/p/b.py", qualname: "B" },
    ] as PageEntry[];
    const flows = [
      { file: "C:/p/flows.py", name: "go", runnable: true, parameters: [] },
      { file: "C:/p/flows.py", name: "needs_value", runnable: true, parameters: [{ name: "x", type: "int", required: true }] },
    ] as FlowEntry[];
    const bindings: Binding[] = [
      { file: "C:/p/a.py", page: "A", flowFile: "C:/p/flows.py", flowName: "go" },
      { file: "C:/p/b.py", page: "B", flowFile: "C:/p/flows.py", flowName: "needs_value" },
    ];
    const result = classifySweepBindings(bindings, pages, flows);
    expect(result.supported).toEqual([bindings[0]]);
    expect(result.skipped.map((page) => page.qualname)).toEqual(["B"]);
  });
});
