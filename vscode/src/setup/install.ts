import { execFile } from "node:child_process";
import * as vscode from "vscode";
import { installArguments } from "../python";
import { DevPackages } from "./devPackages";

declare const __WTK_DEV__: boolean;

/** `0.10.2` against `0.9.9`: negative, zero or positive. Anything that is not a number counts as 0. */
export function compareVersions(first: string, second: string): number {
  const parts = (version: string) => version.split(/[.+-]/).map((part) => Number.parseInt(part, 10) || 0);
  const [a, b] = [parts(first), parts(second)];
  for (let index = 0; index < Math.max(a.length, b.length); index++) {
    const difference = (a[index] ?? 0) - (b[index] ?? 0);
    if (difference) return difference;
  }
  return 0;
}

/** The installed package is older than the one this extension was built for. */
export function isOutdated(installed: string | undefined, required: string | undefined): boolean {
  return !!installed && !!required && compareVersions(installed, required) < 0;
}

/** The tail of pip's error output, which is where the reason is. */
export function installFailure(output: string): string {
  const lines = output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const errors = lines.filter((line) => /^error/i.test(line));
  return (errors.length ? errors : lines).slice(-2).join(" ") || "pip did not say why";
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
  async install(folder: vscode.Uri, python: string): Promise<boolean> {
    if (this.working) return false;
    if (!vscode.workspace.isTrusted) throw new Error("Trust the workspace before installing WinTestKit.");
    this.working = true;
    this.failure = undefined;
    this.changed.fire();
    try {
      let args: string[] | undefined;
      if (typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__ && this.development)
        args = await this.development.arguments(folder);
      else args = await installArguments();
      if (!args) return false;
      this.log.info(`Installing wintestkit: ${python} ${args.join(" ")}`);
      const output = await new Promise<{ ok: boolean; text: string }>((resolve) => {
        execFile(
          python,
          args,
          { timeout: 10 * 60 * 1000, windowsHide: true, maxBuffer: 16 * 1024 * 1024 },
          (error, stdout, stderr) => resolve({ ok: !error, text: `${stdout}\n${stderr}` }),
        );
      });
      this.log.info(output.text);
      if (!output.ok) this.failure = installFailure(output.text);
      return output.ok;
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
