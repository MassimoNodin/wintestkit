import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import * as path from "node:path";
import { identities, redact, truncate, type Counts, type Identities } from "./redact";

export function injectorLogPart(appData: string | undefined, summary: Record<string, unknown>): Part {
  return { name: "Inspector injector log", run: async (): Promise<Record<string, string>> => {
    try {
      if (!appData) { summary.inspectorInjectorLog = "not present"; return {}; }
      return { "logs/snoop-injector.log": await readFile(path.join(appData, "Snoop", "SnoopLog.txt"), "utf8") };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") { summary.inspectorInjectorLog = "not present"; return {}; }
      throw error;
    }
  } };
}

export interface Part { name: string; run: () => Promise<Record<string, string>> }
export async function collect(folder: string, summary: Record<string, unknown>, description: string, parts: Part[], ids: Identities = identities(), now = new Date(), counts: Counts = {}): Promise<void> {
  Object.assign(counts, { home: 0, user: 0, computer: 0, domain: 0, email: 0, secretKeys: 0 });
  const files: { path: string; size: number; sha256: string }[] = [];
  const failures: Record<string, string> = {};
  const clean = (value: string) => truncate(redact(value, ids, counts));
  for (const part of parts) {
    try {
      const entries = await part.run();
      for (const [name, content] of Object.entries(entries)) {
        const data = Buffer.from(clean(content));
        await mkdir(path.join(folder, path.dirname(name)), { recursive: true });
        await writeFile(path.join(folder, name), data);
        files.push({ path: name, size: data.length, sha256: createHash("sha256").update(data).digest("hex") });
      }
    } catch (error) { failures[part.name] = clean(String(error)); }
  }
  const safeSummary = JSON.parse(clean(JSON.stringify(summary))) as Record<string, unknown>;
  const safeDescription = clean(description);
  const createdLocal = now.toString(), createdUtc = now.toISOString();
  const table = Object.entries(safeSummary).map(([key, value]) => `| ${key} | ${JSON.stringify(value).replace(/\|/g, "\\|").replace(/\n/g, " ")} |`).join("\n");
  const readme = `# WinTestKit diagnostics\n\nCreated locally: ${createdLocal}\n\nCreated UTC: ${createdUtc}\n\n## What went wrong\n\n${safeDescription || "No description supplied."}\n\n## Summary\n\n| Item | Value |\n| --- | --- |\n${table}\n\n## Files\n\n${files.map((file) => `- ${file.path} (${file.size} bytes)`).join("\n")}\n- manifest.json\n- README.md\n\n## Collection failures\n\n${Object.entries(failures).map(([name, error]) => `- ${name}: ${error}`).join("\n") || "None."}\n\n## Redactions\n\n${Object.entries(counts).map(([name, count]) => `- ${name}: ${count}`).join("\n")}\n- Secret-looking settings keys are replaced with <redacted>. Review all files before sharing; automatic redaction cannot identify every sensitive value.\n\n## For the agent\n\nStart with the last failure above, errors in logs/wintestkit.log, and the checks in doctor.json. The manifest lists collected files and collection failures.\n`;
  await writeFile(path.join(folder, "README.md"), truncate(readme));
  await writeFile(path.join(folder, "manifest.json"), truncate(JSON.stringify({ schemaVersion: 1, createdLocal, createdUtc, summary: safeSummary, description: safeDescription, files, failures, redactions: counts }, null, 2)));
}
