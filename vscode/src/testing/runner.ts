import {
  execFile,
  spawn,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import { StringDecoder } from "node:string_decoder";
import * as vscode from "vscode";
import type { Project } from "../server/serverManager";
import { terminalText } from "./eventMapper";

export function runArguments(
  url: string,
  nodeids: string[],
  highlight: boolean,
  extraArgs: string[],
  recording = false,
  defaultTrace = false,
): string[] {
  return [
    "-m",
    "wintestkit",
    "run",
    "--events",
    url,
    ...(highlight ? ["--highlight"] : []),
    ...(defaultTrace ? ["--trace", "on"] : []),
    ...extraArgs,
    ...(recording ? ["--trace", "retain-on-failure"] : []),
    "--",
    ...nodeids,
  ];
}
/** Testing-tab runs record a trace unless the project, environment or extra args choose a mode. */
export function tracesByDefault(
  configured: Record<string, unknown>,
  extraArgs: string[],
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  return (
    !("trace" in configured) &&
    !env.WTK_TRACE &&
    !extraArgs.some((arg) => /^--(wtk-)?trace(=|$)/.test(arg))
  );
}
export function killProcessTree(child: ChildProcessWithoutNullStreams): void {
  if (!child.pid) return;
  if (process.platform === "win32")
    execFile(
      "taskkill",
      ["/PID", String(child.pid), "/T", "/F"],
      { windowsHide: true },
      () => {
        child.kill();
      },
    );
  else child.kill("SIGTERM");
}
export async function runProcess(
  project: Project,
  python: string,
  args: string[],
  token: vscode.CancellationToken,
  output: (text: string) => void,
): Promise<number | null> {
  if (token.isCancellationRequested) return null;
  if (!vscode.workspace.isTrusted)
    throw new Error("Trust the workspace before running WinTestKit.");
  const child = spawn(python, args, {
    cwd: project.root.fsPath,
    windowsHide: true,
    env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
  });
  const subscription = token.onCancellationRequested(() =>
    killProcessTree(child),
  );
  const decoders = [new StringDecoder("utf8"), new StringDecoder("utf8")];
  [child.stdout, child.stderr].forEach((stream, index) =>
    stream.on("data", (chunk: Buffer) =>
      output(terminalText(decoders[index].write(chunk))),
    ),
  );
  try {
    return await new Promise<number | null>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (code) => {
        decoders.forEach((decoder) => {
          const text = decoder.end();
          if (text) output(terminalText(text));
        });
        resolve(code);
      });
      if (token.isCancellationRequested) killProcessTree(child);
    });
  } finally {
    subscription.dispose();
  }
}
