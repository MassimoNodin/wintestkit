import * as path from "node:path";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile, lstat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, describe, expect, it } from "vitest";
import { parse } from "smol-toml";
import { cleanReset, planReset } from "../../src/setup/resetFiles";

const temporary: string[] = [];
async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), "wtk-reset-test-"));
  temporary.push(root);
  return root;
}
async function put(root: string, relative: string, content = "custom work") {
  const file = path.join(root, relative);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, content);
}
afterEach(async () => {
  for (const root of temporary.splice(0)) {
    const resolved = path.resolve(root);
    expect(path.dirname(resolved)).toBe(path.resolve(tmpdir()));
    expect(path.basename(resolved)).toMatch(/^(wtk-reset-test-|wintestkit-reset-)/);
    await rm(resolved, { recursive: true, force: true });
  }
});

describe("development introduction cleanup", () => {
  it("backs up all affected files before removing only the advertised paths", async () => {
    const root = await fixture();
    for (const relative of ["pages/custom.py", "flows/main.py", "tests/test_custom.py", "wintestkit.local.yaml", ".claude/skills/wintestkit-tests/SKILL.md", "wtk-results/run.json"])
      await put(root, relative);
    for (const relative of [".git/HEAD", ".venv/keep", ".gitignore", "README.md", ".claude/skills/other/SKILL.md"])
      await put(root, relative, "keep");
    await put(root, "pyproject.toml", '[project]\nname = "demo"\n[tool.wintestkit]\nlaunch = "attach"\n[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n');
    const plan = await planReset(root);
    expect(plan.remove).toContain("tests");
    const backup = await cleanReset(plan);
    temporary.push(backup);
    expect(await readFile(path.join(backup, "tests/test_custom.py"), "utf8")).toBe("custom work");
    expect(await readFile(path.join(backup, "pyproject.toml"), "utf8")).toContain("tool.wintestkit");
    await expect(lstat(path.join(root, "tests"))).rejects.toMatchObject({ code: "ENOENT" });
    expect(parse(await readFile(path.join(root, "pyproject.toml"), "utf8"))).toEqual({ project: { name: "demo" } });
    expect(await readFile(path.join(root, ".git/HEAD"), "utf8")).toBe("keep");
    expect(await readFile(path.join(root, ".venv/keep"), "utf8")).toBe("keep");
    expect(await readFile(path.join(root, ".claude/skills/other/SKILL.md"), "utf8")).toBe("keep");
  });

  it("deletes a starter-only pyproject but preserves customized pytest settings", async () => {
    const root = await fixture();
    await put(root, "pyproject.toml", '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n');
    temporary.push(await cleanReset(await planReset(root)));
    await expect(lstat(path.join(root, "pyproject.toml"))).rejects.toMatchObject({ code: "ENOENT" });
    const customized = '[tool.pytest.ini_options]\naddopts = "-q"\n';
    await put(root, "pyproject.toml", customized);
    expect((await planReset(root)).pyproject).toBeUndefined();
    temporary.push(await cleanReset(await planReset(root)));
    expect(await readFile(path.join(root, "pyproject.toml"), "utf8")).toBe(customized);
  });

  it("refuses changed previews, invalid TOML, filesystem roots and linked targets", async () => {
    const root = await fixture();
    const plan = await planReset(root);
    await put(root, "wintestkit.yaml");
    await expect(cleanReset(plan)).rejects.toThrow("changed");
    await expect(planReset(path.parse(root).root)).rejects.toThrow("filesystem root");
    await put(root, "pyproject.toml", "[invalid");
    await expect(planReset(root)).rejects.toThrow();
    const outside = await fixture();
    const linked = await fixture();
    await symlink(outside, path.join(linked, "pages"), "junction");
    await expect(planReset(linked)).rejects.toThrow("symbolic links or junctions");
    const parentLinked = await fixture();
    await symlink(outside, path.join(parentLinked, ".claude"), "junction");
    await expect(planReset(parentLinked)).rejects.toThrow("symbolic links or junctions");
  });
});
