import { describe, expect, it } from "vitest";
import { bindPageFlow, type Binding } from "../../src/editor/checkAfterFlow";

describe("explicit check-after-flow bindings", () => {
  it("remembers one selected flow per class and preserves other classes", () => {
    const first: Binding = {
      file: "C:/p/a.py", page: "A", flowFile: "C:/p/flows.py", flowName: "old",
    };
    const other: Binding = {
      file: "C:/p/b.py", page: "B", flowFile: "C:/p/flows.py", flowName: "other",
    };
    expect(
      bindPageFlow([first, other], { file: "c:/p/a.py", page: "A" }, {
        file: "C:/p/flows.py", name: "reach_a",
      }),
    ).toEqual([
      other,
      { file: "c:/p/a.py", page: "A", flowFile: "C:/p/flows.py", flowName: "reach_a" },
    ]);
  });
});
