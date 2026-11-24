import { execFile } from "node:child_process";
import * as path from "node:path";
import * as vscode from "vscode";
import { checkWintestkit, installArguments, requirePip } from "../python";
import { CompatibilityError, packageCompatibility, PYTHON_REQUIREMENT } from "../compatibility";
import { DevPackages } from "./devPackages";

declare const __WTK_DEV__: boolean;

/** The tail of pip's error output, which is where the reason is. */
export function installFailure(output: string): string {
  const lines = output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const errors = lines.filter((line) => /^error/i.test(line));
  return (errors.length ? errors : lines).slice(-2).join(" ") || "pip did not say why";
}

export interface InspectorHolder { pid: number; name: string; started: string }

export function describeHolders(holders: InspectorHolder[]): string {
  return holders.map((holder) => `${holder.name} (PID ${holder.pid})`).join(", ");
}

async function inspectorHelper(python: string, action: string, holders?: InspectorHolder[]): Promise<InspectorHolder[]> {
  const script = path.join(__dirname, "..", "media", "inspector-locks.py");
  return await new Promise((resolve, reject) => {
    execFile(python, ["-I", script, action, ...(holders ? [JSON.stringify(holders)] : [])],
      { windowsHide: true, timeout: 20000 }, (error, stdout, stderr) => {
        if (error) return reject(new Error(`Inspector lock check failed: ${stderr || error.message}`));
        try {
          const result: unknown = JSON.parse(stdout);
          if (!Array.isArray(result) || !result.every((item: unknown) =>
            typeof item === "object" && item !== null &&
            typeof (item as InspectorHolder).pid === "number" &&
            typeof (item as InspectorHolder).name === "string" &&
            typeof (item as InspectorHolder).started === "string")) throw new Error("Invalid helper output");
          resolve(result as InspectorHolder[]);
        } catch (parseError) { reject(parseError); }
      });
  });
}

export async function confirmInspectorClose(
  python: string, helper = inspectorHelper,
): Promise<boolean> {
  // A failed check must not block the install: pip then reports any lock itself.
  const holders = await helper(python, "list").catch(() => [] as InspectorHolder[]);
  if (!holders.length) return true;
  const choice = await vscode.window.showWarningMessage(
    `${describeHolders(holders)} has the WinTestKit inspector loaded, so the upgrade cannot replace it. Close it and install?`,
    { modal: true }, "Close and install", "Cancel",
  );
  if (choice !== "Close and install") return false;
  const remaining = await helper(python, "close", holders);
  if (!remaining.length) return true;
  const force = await vscode.window.showWarningMessage(
    `${describeHolders(remaining)} did not close. Force close and install?`,
    { modal: true }, "Force close", "Cancel",
  );
  if (force !== "Force close") return false;
  const stillRunning = await helper(python, "force", remaining);
  if (stillRunning.length) throw new Error(`Could not close ${describeHolders(stillRunning)}.`);
  return true;
}

/** Installs or updates the wintestkit package in the interpreter the tests use, without a terminal. */
export class PackageInstaller implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private working = false;
  private failure?: string;
  readonly development?: DevPackages;
  constructor(private readonly log: vscode.LogOutputChannel, state?: vscode.Memento) {
    if (typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__ && state)
      this.development = new DevPackages(state);
  }
  get busy(): boolean {
    return this.working;
  }
  /** Why the last attempt failed, until the next one starts. */
  get error(): string | undefined {
    return this.failure;
  }
  async selectSource(folder: vscode.Uri, source: "remote" | "local"): Promise<void> {
    if (!(typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__) || !this.development || this.working) return;
    if (!vscode.workspace.isTrusted) throw new Error("Trust the workspace before selecting a package source.");
    this.working = true;
    this.changed.fire();
    try {
      await this.development.select(folder, source);
      this.failure = undefined;
    } finally {
      this.working = false;
      this.changed.fire();
    }
  }
  /** Returns whether pip succeeded. */
  async install(folder: vscode.Uri, python: string, upgrade = false): Promise<boolean> {
    if (this.working) return false;
    if (!vscode.workspace.isTrusted) throw new Error("Trust the workspace before installing WinTestKit.");
    this.working = true;
    this.failure = undefined;
    this.changed.fire();
    try {
      let args: string[] | undefined;
      if (!upgrade && typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__ && this.development)
        args = await this.development.arguments(folder);
      else args = await installArguments();
      if (!args) return false;
      if (!(await confirmInspectorClose(python))) return false;
      const command = await requirePip(python, args);
      this.log.info(`Installing wintestkit: ${[command.executable, ...command.args].map((part) => JSON.stringify(part)).join(" ")}`);
      const output = await new Promise<{ ok: boolean; text: string }>((resolve) => {
        execFile(
          command.executable,
          command.args,
          { timeout: 10 * 60 * 1000, windowsHide: true, maxBuffer: 16 * 1024 * 1024 },
          (error, stdout, stderr) => resolve({ ok: !error, text: `${stdout}\n${stderr}` }),
        );
      });
      this.log.info(`Install ${output.ok ? "succeeded" : "failed"}: ${output.text}`);
      if (!output.ok) {
        if (/wintestkit[_-]inspector/i.test(output.text) && /(?:access (?:is )?denied|winerror\s*(?:5|32))/i.test(output.text)) {
          const holders = await inspectorHelper(python, "list").catch(() => []);
          this.failure = `The inspector files are locked${holders.length ? " by " + describeHolders(holders) : " by another process"}. Close the application and try again.`;
        } else this.failure = "Could not install " + PYTHON_REQUIREMENT + " in " + python + ": " + installFailure(output.text);
        return false;
      }
      await inspectorHelper(python, "cleanup").catch((error: unknown) => this.log.info(`Cleanup failed: ${String(error)}`));
      const installed = await checkWintestkit(python);
      const issue = packageCompatibility(installed.installed ? installed.version : undefined, installed.inspectorVersion);
      if (issue) throw new CompatibilityError(issue, python);
      return true;
    } catch (error) {
      this.failure = error instanceof Error ? error.message : String(error);
      this.log.info(this.failure);
      return false;
    } finally {
      this.working = false;
      this.changed.fire();
    }
  }
  dispose(): void {
    this.changed.dispose();
  }
}
