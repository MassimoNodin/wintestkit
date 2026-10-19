import * as path from "node:path";
import { cp, lstat, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { parse, stringify } from "smol-toml";

const TARGETS = [
  "pages", "flows", "tests", "wintestkit.yaml", "wintestkit.local.yaml",
  "wintestkit.local.toml", ".claude/skills/wintestkit-tests", "wtk-report", "wtk-results",
  ".pytest_cache",
];

function table(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value) && !(value instanceof Date);
}

async function present(file: string): Promise<boolean> {
  try {
    await lstat(file);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

async function checkedPath(root: string, relative: string): Promise<string> {
  const target = path.resolve(root, relative);
  const within = path.relative(root, target);
  if (!within || within.startsWith("..") || path.isAbsolute(within))
    throw new Error("Reset target is outside the selected workspace.");
  let current = root;
  for (const component of within.split(path.sep)) {
    current = path.join(current, component);
    if (await present(current) && (await lstat(current)).isSymbolicLink())
      throw new Error("Reset refuses symbolic links or junctions: " + current);
  }
  return target;
}

export interface ResetPlan {
  root: string;
  remove: string[];
  pyproject?: { before: string; after?: string };
}

export async function planReset(folder: string): Promise<ResetPlan> {
  const root = await realpath(folder);
  if (root === path.parse(root).root) throw new Error("Cannot reset a filesystem root.");
  const remove: string[] = [];
  for (const relative of TARGETS)
    if (await present(await checkedPath(root, relative))) remove.push(relative);
  const plan: ResetPlan = { root, remove };
  const file = await checkedPath(root, "pyproject.toml");
  if (await present(file)) {
    const before = await readFile(file, "utf8");
    const document = parse(before);
    const tool = document.tool;
    if (table(tool)) {
      let changed = false;
      if ("wintestkit" in tool) {
        delete tool.wintestkit;
        changed = true;
      }
      const pytest = tool.pytest;
      if (table(pytest)) {
        const options = pytest.ini_options;
        if (table(options) &&
            Object.keys(options).length === 2 &&
            JSON.stringify(options.pythonpath) === '["."]' &&
            JSON.stringify(options.testpaths) === '["tests"]') {
          delete pytest.ini_options;
          if (!Object.keys(pytest).length) delete tool.pytest;
          changed = true;
        }
      }
      if (changed) {
        if (!Object.keys(tool).length) delete document.tool;
        plan.pyproject = { before, after: Object.keys(document).length ? stringify(document) : undefined };
      }
    }
  }
  return plan;
}

export async function cleanReset(plan: ResetPlan): Promise<string> {
  const current = await planReset(plan.root);
  if (JSON.stringify(current) !== JSON.stringify(plan))
    throw new Error("Repository changed since the cleanup preview. Run reset again.");
  const backup = await mkdtemp(path.join(tmpdir(), "wintestkit-reset-"));
  for (const relative of [...plan.remove, ...(plan.pyproject ? ["pyproject.toml"] : [])]) {
    const source = await checkedPath(plan.root, relative);
    const destination = path.join(backup, relative);
    await mkdir(path.dirname(destination), { recursive: true });
    await cp(source, destination, { recursive: true, dereference: false });
  }
  try {
    for (const relative of plan.remove)
      await rm(await checkedPath(plan.root, relative), { recursive: true });
    if (plan.pyproject) {
      const file = await checkedPath(plan.root, "pyproject.toml");
      if (plan.pyproject.after === undefined) await rm(file);
      else await writeFile(file, plan.pyproject.after, "utf8");
    }
  } catch (error) {
    throw new Error("Reset failed. Restore files from " + backup + ": " + String(error));
  }
  return backup;
}
