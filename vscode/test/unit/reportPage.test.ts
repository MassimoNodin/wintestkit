import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildReportHtml,
  readResults,
  scriptSafeJson,
  TREE_TEXT_LIMIT,
} from "../../src/reportPage";

const TEMPLATE = path.resolve(__dirname, "../../../python/src/wintestkit/report/template.html");

let dir: string;
beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "wtk-report-"));
});
afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

const save = (results: unknown) => writeFile(path.join(dir, "results.json"), JSON.stringify(results));
const embedded = (html: string): { tests: Record<string, unknown>[] } => {
  const match = /<script type="application\/json" id="wtk-data">([\s\S]*?)<\/script>/.exec(html);
  return JSON.parse(match![1]);
};

describe("report page built from results.json", () => {
  it("fills the template with the saved results", async () => {
    await save({ version: 1, tests: [{ id: "t.py::a", name: "a", outcome: "passed" }] });
    const html = await buildReportHtml(dir, await readFile(TEMPLATE, "utf8"));
    expect(html).not.toContain("__WTK_DATA__");
    expect(embedded(html).tests[0]).toMatchObject({ id: "t.py::a", outcome: "passed" });
  });

  it("keeps test content from ending the script element or being run", async () => {
    await save({ version: 1, tests: [{ id: "x", message: "</script><img src=x onerror=alert(1)>$&" }] });
    const html = await buildReportHtml(dir, "<script type=\"application/json\" id=\"wtk-data\">__WTK_DATA__</script>");
    expect(html.match(/<\/script>/g)).toHaveLength(1);
    expect(html).not.toContain("<img");
    expect(embedded(html).tests[0].message).toBe("</script><img src=x onerror=alert(1)>$&");
    expect(scriptSafeJson({ a: "<b>" })).toBe('{"a":"\\u003cb>"}');
  });

  it("embeds each UI tree from inside the report folder, capped like the Python report", async () => {
    await mkdir(path.join(dir, "artifacts"));
    await writeFile(path.join(dir, "artifacts", "tree.txt"), 'Window "App"\n');
    await writeFile(path.join(dir, "artifacts", "big.txt"), "x".repeat(TREE_TEXT_LIMIT + 10));
    await save({
      version: 1,
      tests: [
        { id: "a", treeDump: "artifacts/tree.txt" },
        { id: "b", treeDump: "artifacts/big.txt" },
        { id: "c", treeDump: "../outside.txt" },
        { id: "d", treeDump: "artifacts/missing.txt" },
        { id: "e" },
      ],
    });
    const tests = embedded(await buildReportHtml(dir, "<script type=\"application/json\" id=\"wtk-data\">__WTK_DATA__</script>")).tests;
    expect(tests[0]).toMatchObject({ treeText: 'Window "App"\n', treeTextTruncated: false });
    expect(tests[1].treeTextTruncated).toBe(true);
    expect((tests[1].treeText as string).length).toBe(TREE_TEXT_LIMIT);
    for (const untouched of tests.slice(2)) expect(untouched).not.toHaveProperty("treeText");
  });

  it("rejects missing or unsupported results", async () => {
    await expect(readResults(dir)).rejects.toThrow();
    await save({ version: 2 });
    await expect(readResults(dir)).rejects.toThrow("version 1");
    await writeFile(path.join(dir, "results.json"), "[]");
    await expect(readResults(dir)).rejects.toThrow("not a JSON object");
  });
});
