import { execFile } from "node:child_process";
import { mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { parse as parseToml, stringify as tomlStringify } from "smol-toml";
import { parse as parseYaml, stringify as yamlStringify } from "yaml";
import { checkWintestkit, getInterpreter } from "../python";
import { configurationNames } from "../settings/files";
import policy from "../compatibility.json";
import { collect, injectorLogPart, type Part } from "./collect";
import { redactSecrets } from "./redact";
import { zip } from "./zip";

function run(executable: string, args: string[], cwd?: string): Promise<string> {
  return new Promise((resolve, reject) => execFile(executable, args, { cwd, timeout: 30000, maxBuffer: 10 * 1024 * 1024, windowsHide: true }, (error, stdout) => {
    if (error && !stdout) reject(error); else resolve(stdout);
  }));
}
async function findLog(dir: string, depth: number): Promise<{ file: string; time: number }[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const found: { file: string; time: number }[] = [];
  for (const entry of entries) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory() && depth > 0) found.push(...await findLog(file, depth - 1).catch(() => []));
    else if (entry.isFile() && /(?:^|[-\d ])WinTestKit\.log$/i.test(entry.name)) found.push({ file, time: (await stat(file)).mtimeMs });
  }
  return found;
}
async function diskFiles(dir: string, prefix = ""): Promise<{ name: string; data: Buffer }[]> {
  const result: { name: string; data: Buffer }[] = [];
  for (const entry of await readdir(path.join(dir, prefix), { withFileTypes: true })) {
    const name = path.posix.join(prefix, entry.name);
    if (entry.isDirectory()) result.push(...await diskFiles(dir, name));
    else if (entry.isFile()) result.push({ name, data: await readFile(path.join(dir, name)) });
  }
  return result;
}
export async function saveDiagnostics(context: vscode.ExtensionContext, folder: vscode.Uri | undefined, state: () => unknown): Promise<void> {
  const options = [
    { label: "WinTestKit log", id: "log", picked: true },
    { label: "Inspector injector log", id: "injector", picked: true },
    { label: "Doctor checks", id: "doctor", picked: true },
    { label: "WinTestKit settings", id: "settings", picked: true },
    { label: "Spy trace", id: "trace", description: "may contain values read from your application", picked: false },
  ];
  const selected = await vscode.window.showQuickPick(options, { canPickMany: true, placeHolder: "Choose diagnostics to include (environment is always included)" });
  if (!selected) return;
  const description = await vscode.window.showInputBox({ prompt: "What went wrong? (optional)" });
  if (description === undefined) return;
  const chosen = new Set(selected.map((item) => item.id));
  const root = folder ?? vscode.workspace.workspaceFolders?.[0]?.uri;
  let python: string | undefined;
  const summary: Record<string, unknown> = { extension: context.extension.packageJSON.version, vscode: vscode.version, os: `${os.type()} ${os.release()} ${os.arch()}`, compatibility: policy, state: state() };
  const redactions: Record<string, number> = {};
  const parts: Part[] = [{ name: "Environment", run: async () => {
    if (root) python = await getInterpreter(root);
    summary.interpreter = python ?? "Not selected";
    if (python) {
      const [version, packages] = await Promise.all([run(python, ["--version"]), checkWintestkit(python)]);
      summary.pythonVersion = version.trim(); summary.packages = packages;
    }
    return {};
  } }];
  if (chosen.has("log")) parts.push({ name: "WinTestKit log", run: async () => {
    const candidates: { file: string; time: number }[] = await findLog(context.logUri.fsPath, 3).catch(() => []);
    if (!candidates.length) candidates.push(...await findLog(path.dirname(context.logUri.fsPath), 4));
    const latest = candidates.sort((a, b) => b.time - a.time)[0];
    if (!latest) throw new Error("WinTestKit log file was not found");
    return { "logs/wintestkit.log": await readFile(latest.file, "utf8") };
  } });
  if (chosen.has("injector")) parts.push(injectorLogPart(process.env.APPDATA, summary));
  if (chosen.has("doctor")) parts.push({ name: "Doctor", run: async () => {
    if (!python) throw new Error("No interpreter selected");
    if (!vscode.workspace.isTrusted) throw new Error("Workspace trust is required to run doctor");
    return { "doctor.json": await run(python, ["-m", "wintestkit", "doctor", "--json"], root?.fsPath) };
  } });
  if (chosen.has("settings")) {
    parts.push({ name: "VS Code settings", run: async () => {
      const properties = context.extension.packageJSON.contributes.configuration.properties as Record<string, unknown>;
      const config = vscode.workspace.getConfiguration(undefined, root);
      return { "settings/vscode-settings.json": JSON.stringify(redactSecrets(Object.fromEntries(Object.keys(properties).filter((key) => key.startsWith("wintestkit.")).map((key) => [key, config.get(key)])), redactions), null, 2) };
    } });
    if (root) for (const name of configurationNames) parts.push({ name: name, run: async () => {
      let text: string;
      try { text = await readFile(path.join(root.fsPath, name), "utf8"); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return {}; throw error; }
      const parsed = name.endsWith(".toml") ? parseToml(text) : parseYaml(text);
      // A project file may contain unrelated tool settings and credentials: collect only this tool's section.
      const value = name === "pyproject.toml" ? { tool: { wintestkit: (parsed as { tool?: { wintestkit?: unknown } }).tool?.wintestkit ?? {} } } : parsed;
      const safe = redactSecrets(value, redactions);
      return { [`settings/${name}`]: name.endsWith(".toml") ? tomlStringify(safe as Parameters<typeof tomlStringify>[0]) : yamlStringify(safe) };
    } });
  }
  if (chosen.has("trace")) parts.push({ name: "Spy trace", run: async () => {
    const file = vscode.workspace.getConfiguration("wintestkit.spy", root).get<string>("traceFile", "");
    if (!file) throw new Error("No Spy trace file configured");
    return { [`logs/spy-trace${path.extname(file) || ".log"}`]: await readFile(path.isAbsolute(file) ? file : path.resolve(root?.fsPath ?? os.homedir(), file), "utf8") };
  } });
  const temp = await mkdtemp(path.join(os.tmpdir(), "wintestkit-diagnostics-"));
  try {
    await collect(temp, summary, description, parts, undefined, undefined, redactions);
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(temp, "README.md")));
    await vscode.window.showTextDocument(doc, { preview: true });
    for (;;) {
      const action = await vscode.window.showInformationMessage("Review the diagnostics, then save them as a zip.", "Save zip…", "Open folder", "Cancel");
      if (action === "Open folder") { await vscode.commands.executeCommand("revealFileInOS", vscode.Uri.file(temp)); continue; }
      if (action !== "Save zip…") { await rm(temp, { recursive: true, force: true }); return; }
      const now = new Date(), stamp = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,"0")}${String(now.getDate()).padStart(2,"0")}-${String(now.getHours()).padStart(2,"0")}${String(now.getMinutes()).padStart(2,"0")}${String(now.getSeconds()).padStart(2,"0")}`;
      const downloads = path.join(os.homedir(), "Downloads");
      const base = await stat(downloads).then((s) => s.isDirectory() ? downloads : os.homedir(), () => os.homedir());
      const destination = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(base, `wintestkit-diagnostics-${stamp}.zip`)), filters: { Zip: ["zip"] } });
      if (!destination) continue;
      await writeFile(destination.fsPath, zip(await diskFiles(temp)));
      await rm(temp, { recursive: true, force: true });
      const next = await vscode.window.showInformationMessage("Diagnostics zip saved.", "Reveal in Explorer", "Copy path");
      if (next === "Reveal in Explorer") await vscode.commands.executeCommand("revealFileInOS", destination);
      if (next === "Copy path") await vscode.env.clipboard.writeText(destination.fsPath);
      return;
    }
  } catch (error) { await rm(temp, { recursive: true, force: true }); throw error; }
}

