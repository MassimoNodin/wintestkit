import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import * as vscode from "vscode";
import { checkWintestkit, getInterpreter } from "../python";
import type { InitializeResult } from "../protocol/generated";
import { JsonRpcClient, LineSplitter, RpcError } from "./jsonrpc";

export interface Project {
  root: vscode.Uri;
  name: string;
}
export interface ServerConnection {
  client: JsonRpcClient;
  python: string;
  initialized: InitializeResult;
}
export type ServerState = "ready" | "error" | "not-installed" | "stopped";
interface Entry {
  project: Project;
  promise?: Promise<ServerConnection>;
  connection?: ServerConnection;
  process?: ChildProcessWithoutNullStreams;
  restart?: ReturnType<typeof setTimeout>;
  crashes: number[];
  generation: number;
  state: ServerState;
  blocked?: boolean;
  startupError?: RpcError;
}

export class ServerManager implements vscode.Disposable {
  private readonly entries = new Map<string, Entry>();
  private readonly changed = new vscode.EventEmitter<Project>();
  readonly onDidChange = this.changed.event;
  private disposed = false;
  constructor(private readonly log: vscode.LogOutputChannel) {}
  state(project: Project): ServerState {
    return this.entries.get(project.root.toString())?.state ?? "stopped";
  }
  async release(project: Project): Promise<void> {
    const key = project.root.toString();
    const entry = this.entries.get(key);
    if (!entry) return;
    this.entries.delete(key);
    await this.stop(entry);
  }
  get(project: Project): Promise<ServerConnection> {
    if (this.disposed)
      return Promise.reject(new Error("server manager stopped"));
    if (!vscode.workspace.isTrusted)
      return Promise.reject(
        new Error("Trust the workspace before running WinTestKit."),
      );
    const key = project.root.toString();
    let entry = this.entries.get(key);
    if (!entry) {
      entry = {
        project,
        crashes: [],
        generation: 0,
        state: "stopped",
      };
      this.entries.set(key, entry);
    }
    if (entry.startupError) return Promise.reject(entry.startupError);
    if (entry.blocked)
      return Promise.reject(
        new Error(
          "WinTestKit server stopped after repeated crashes; restart it manually",
        ),
      );
    if (entry.restart)
      return Promise.reject(new Error("WinTestKit server is restarting"));
    if (!entry.promise) {
      const current = entry;
      const generation = current.generation;
      current.promise = this.start(current).catch((error) => {
        if (generation !== current.generation) throw error;
        current.promise = undefined;
        if (current.state !== "not-installed") current.state = "error";
        this.changed.fire(project);
        throw error;
      });
    }
    return entry.promise ?? Promise.reject(new Error("server start cancelled"));
  }
  private async start(entry: Entry): Promise<ServerConnection> {
    const generation = entry.generation;
    const python = await getInterpreter(entry.project.root);
    if (!python) throw new Error("Select a Python interpreter first.");
    const packageInfo = await checkWintestkit(python);
    if (this.disposed || generation !== entry.generation)
      throw new Error("server start cancelled");
    if (!packageInfo.installed) {
      entry.state = "not-installed";
      // The guided setup notices this and offers to fix it, so there is no message here.
      throw new Error("wintestkit is not installed");
    }
    const level = vscode.workspace
      .getConfiguration("wintestkit", entry.project.root)
      .get<string>("server.logLevel", "info");
    const processHandle = spawn(
      python,
      [
        "-m",
        "wintestkit",
        "--log-level",
        level.toUpperCase(),
        "serve",
        "--stdio",
      ],
      {
        cwd: entry.project.root.fsPath,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1",
          PYTHONIOENCODING: "utf-8",
        },
        windowsHide: true,
      },
    );
    entry.process = processHandle;
    this.log.info(
      "[" +
        entry.project.name +
        "] Starting server for " +
        entry.project.root.fsPath +
        " using " +
        python +
        " (pid " +
        processHandle.pid +
        ")",
    );
    let startupRejected = false;
    const client = new JsonRpcClient((line) => processHandle.stdin.write(line));
    const stdout = new LineSplitter((line) => client.handleLine(line));
    const stderr = new LineSplitter((line) =>
      this.log.info(`[${entry.project.name}] ${line}`),
    );
    processHandle.stdout.on("data", (chunk) => stdout.push(chunk));
    processHandle.stderr.on("data", (chunk) => stderr.push(chunk));
    processHandle.stdin.on("error", (error) => this.log.error(String(error)));
    processHandle.once("error", (error) => {
      this.log.error(String(error));
      client.dispose();
    });
    processHandle.once("close", (code, signal) => {
      stdout.end();
      stderr.end();
      client.dispose();
      if (this.disposed || generation !== entry.generation) return;
      entry.connection = undefined;
      entry.promise = undefined;
      entry.process = undefined;
      entry.state = "error";
      if (startupRejected) return;
      this.log.error(
        "[" +
          entry.project.name +
          "] Server stopped unexpectedly for " +
          entry.project.root.fsPath +
          " (exit code " +
          code +
          ", signal " +
          signal +
          ")",
      );
      entry.crashes = entry.crashes.filter(
        (timestamp) => Date.now() - timestamp < 60000,
      );
      entry.crashes.push(Date.now());
      this.changed.fire(entry.project);
      if (entry.crashes.length >= 3) {
        entry.blocked = true;
        void vscode.window
          .showErrorMessage(
            "WinTestKit server for " +
              entry.project.name +
              " repeatedly stopped.",
            "Show Output",
            "Restart",
          )
          .then((choice) => {
            if (choice === "Show Output") this.log.show();
            if (choice === "Restart")
              void this.restart(entry.project).catch((error) =>
                this.log.error(String(error)),
              );
          });
      } else {
        entry.restart = setTimeout(
          () => {
            entry.restart = undefined;
            void this.get(entry.project).catch((error) =>
              this.log.error(String(error)),
            );
          },
          1000 * 2 ** (entry.crashes.length - 1),
        );
      }
    });
    let initialized: InitializeResult;
    try {
      initialized = await client.request<InitializeResult>("initialize", {
        root: entry.project.root.fsPath,
      });
      if (initialized.protocolVersion !== 1) {
        void vscode.window.showErrorMessage(
          "WinTestKit extension and Python package versions are incompatible. Update the package from the interpreter tile in Test Target.",
        );
        throw new Error("incompatible WinTestKit protocol version");
      }
    } catch (error) {
      if (
        !this.disposed &&
        generation === entry.generation &&
        error instanceof RpcError &&
        error.code !== -1
      ) {
        startupRejected = true;
        entry.startupError = error;
        this.log.error(
          "[" +
            entry.project.name +
            "] Server initialization rejected for " +
            entry.project.root.fsPath +
            ": " +
            String(error),
        );
      }
      client.dispose();
      processHandle.kill();
      throw error;
    }
    if (this.disposed || generation !== entry.generation) {
      client.dispose();
      processHandle.kill();
      throw new Error("server start cancelled");
    }
    entry.connection = { client, python, initialized };
    entry.state = "ready";
    this.changed.fire(entry.project);
    return entry.connection;
  }
  async restartIfInterpreterChanged(project: Project): Promise<void> {
    const entry = this.entries.get(project.root.toString());
    if (!entry?.promise) return;
    let connection: ServerConnection;
    try {
      connection = await entry.promise;
    } catch {
      return;
    }
    const python = await getInterpreter(project.root);
    if (
      !this.disposed &&
      entry.connection === connection &&
      python !== connection.python
    )
      await this.restart(project);
  }
  async restart(project: Project): Promise<ServerConnection> {
    const entry = this.entries.get(project.root.toString());
    if (entry) {
      await this.stop(entry);
      entry.crashes = [];
      entry.blocked = false;
    }
    return this.get(project);
  }
  private async stop(entry: Entry): Promise<void> {
    entry.generation++;
    if (entry.restart) clearTimeout(entry.restart);
    entry.restart = undefined;
    const connection = entry.connection;
    const processHandle = entry.process;
    entry.connection = undefined;
    entry.promise = undefined;
    entry.process = undefined;
    entry.state = "stopped";
    entry.startupError = undefined;
    if (connection) {
      try {
        await connection.client.request("shutdown", {}, 1000);
      } catch {
        this.log.debug("server shutdown grace elapsed");
      }
      connection.client.dispose();
    }
    processHandle?.kill();
  }
  async stopAll(): Promise<void> {
    await Promise.all([...this.entries.values()].map((entry) => this.stop(entry)));
  }
  async shutdown(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    await Promise.all(
      [...this.entries.values()].map((entry) => this.stop(entry)),
    );
    this.changed.dispose();
  }
  dispose(): void {
    void this.shutdown();
  }
}
