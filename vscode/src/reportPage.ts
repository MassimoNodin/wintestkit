import { open, readFile } from "node:fs/promises";
import * as path from "node:path";

/** The most UI tree text embedded per test, matching the Python report. */
export const TREE_TEXT_LIMIT = 512 * 1024;

type Json = Record<string, unknown>;

/** `results.json` as written by a run; throws when it is missing or not a version 1 object. */
export async function readResults(dir: string): Promise<Json> {
  const parsed: unknown = JSON.parse(await readFile(path.join(dir, "results.json"), "utf8"));
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
    throw new Error("results.json is not a JSON object");
  const results = parsed as Json;
  if (results.version !== 1) throw new Error("results.json is not version 1");
  return results;
}

async function readLimited(file: string, limit: number): Promise<Buffer> {
  const handle = await open(file, "r");
  try {
    const buffer = Buffer.alloc(limit + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    return buffer.subarray(0, bytesRead);
  } finally {
    await handle.close();
  }
}

/** Adds each test's UI tree text, read from inside `dir` only, as the Python report does. */
async function withTrees(results: Json, dir: string): Promise<Json> {
  const root = path.resolve(dir);
  const tests = Array.isArray(results.tests) ? (results.tests as Json[]) : [];
  const embedded = await Promise.all(
    tests.map(async (test) => {
      if (typeof test?.treeDump !== "string" || !test.treeDump) return test;
      const source = path.resolve(root, test.treeDump);
      const inside = path.relative(root, source);
      if (inside.startsWith("..") || path.isAbsolute(inside)) return test;
      try {
        const content = await readLimited(source, TREE_TEXT_LIMIT);
        return {
          ...test,
          treeText: content.subarray(0, TREE_TEXT_LIMIT).toString("utf8"),
          treeTextTruncated: content.length > TREE_TEXT_LIMIT,
        };
      } catch {
        return test;
      }
    }),
  );
  return { ...results, tests: embedded };
}

/** JSON that can sit inside a `<script>` element without ever ending it. */
export function scriptSafeJson(value: unknown): string {
  return JSON.stringify(value).replace(/<\//g, "<\\/").replace(/</g, "\\u003c");
}

/** The self-contained report page for the results saved in `dir`. */
export async function buildReportHtml(dir: string, template: string): Promise<string> {
  const results = await withTrees(await readResults(dir), dir);
  const data = scriptSafeJson(results);
  return template.replace("__WTK_DATA__", () => data);
}
