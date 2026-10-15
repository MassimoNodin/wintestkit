import { describe, expect, it, vi } from "vitest";
vi.mock("vscode", () => ({}));
import { pickProject } from "../../src/projects";

describe("project selection", () => {
  it("uses the deepest root and respects directory boundaries", () => {
    expect(
      pickProject(
        ["C:/repo", "C:/repo/nested"],
        "C:/repo/nested/page.py",
        true,
      ),
    ).toBe("C:/repo/nested");
    expect(
      pickProject(["C:/repo"], "C:/repository/test.py", true),
    ).toBeUndefined();
  });
  it("normalizes Windows casing and separators", () => {
    expect(pickProject(["C:/Repo"], "c:/repo/test.py", true)).toBe("C:/Repo");
    expect(pickProject(["C:/Repo"], "c:/repo/test.py", false)).toBeUndefined();
  });
  it("accepts a root itself but rejects outside paths", () => {
    expect(pickProject(["C:/repo/"], "C:/repo", true)).toBe("C:/repo/");
    expect(pickProject([], "C:/repo", true)).toBeUndefined();
    expect(pickProject(["C:/repo"], "D:/repo/test.py", true)).toBeUndefined();
  });
});
