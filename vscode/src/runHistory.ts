import { existsSync } from "node:fs";
import { rm } from "node:fs/promises";
import * as path from "node:path";

const KEY = "wintestkit.runHistory";
export const RUN_NAME_PREFIX = "WinTestKit run";
/** Failure messages carry their run's name as `wintestkit.run:<name>` so a button on them can find the run. */
export const RUN_CONTEXT_PREFIX = "wintestkit.run:";
/** How many runs keep their report before the oldest are removed. */
export const DEFAULT_KEEP_RUNS = 20;

export interface RunProject {
  /** The project's name in the editor, for the pick list. */
  label: string;
  /** The folder holding this project's `results.json`, `index.html` and `artifacts`. */
  dir: string;
  failed?: number;
  passed?: number;
}

export interface RunEntry {
  name: string;
  at: number;
  projects: Record<string, RunProject>;
}

export interface HistoryState {
  get<T>(key: string): T | undefined;
  update(key: string, value: unknown): PromiseLike<void>;
}

export interface HistoryIo {
  exists(file: string): boolean;
  remove(dir: string): Promise<void>;
}

const realIo: HistoryIo = {
  exists: existsSync,
  remove: (dir) => rm(dir, { recursive: true, force: true }),
};

/** `<project>/<report dir>/runs/<run name made safe for a path>`. */
export function runDirectory(
  root: string,
  reportDir: string,
  name: string,
): string {
  const slug = name
    .slice(RUN_NAME_PREFIX.length)
    .replace(/[^0-9A-Za-z]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return path.resolve(root, reportDir, "runs", slug || "run");
}

/**
 * What a button on a Test Results row passes: the run's name arrives in an object next to the test,
 * either as a separate argument or wrapped together with it, so look through whatever came.
 */
export function runNameFrom(args: unknown, depth = 0): string | undefined {
  if (!args || typeof args !== "object" || depth > 4) return undefined;
  const direct = (args as { testRunName?: unknown }).testRunName;
  if (typeof direct === "string" && direct) return direct;
  const context = (args as { contextValue?: unknown }).contextValue;
  if (typeof context === "string" && context.startsWith(RUN_CONTEXT_PREFIX))
    return context.slice(RUN_CONTEXT_PREFIX.length);
  for (const value of Object.values(args)) {
    const found = runNameFrom(value, depth + 1);
    if (found) return found;
  }
  return undefined;
}

/** The first test item in the arguments, if VS Code passed the real one. */
export function testItemFrom(
  args: unknown[],
): { id: string; label: string } | undefined {
  return args.find(
    (arg): arg is { id: string; label: string } =>
      !!arg &&
      typeof arg === "object" &&
      "id" in arg &&
      "label" in arg &&
      !("testRunName" in arg),
  );
}

/**
 * The runs started from the Testing view, each with its own report folder. VS Code hands a
 * button on a test row the name of the run it belongs to, and that name is the key here.
 */
export class RunHistory {
  private readonly entries = new Map<string, RunEntry>();
  private readonly listeners = new Set<(removed?: RunEntry) => void>();
  private readonly discards = new Map<string, Promise<void>>();

  onDidChange(listener: (removed?: RunEntry) => void): { dispose(): void } {
    this.listeners.add(listener);
    return { dispose: () => this.listeners.delete(listener) };
  }

  all(): RunEntry[] {
    return [...this.entries.values()];
  }

  constructor(
    private readonly state?: HistoryState,
    private readonly io: HistoryIo = realIo,
    private readonly clock: () => Date = () => new Date(),
  ) {
    const saved = state?.get<Record<string, RunEntry>>(KEY) ?? {};
    for (const entry of Object.values(saved)) {
      const alive = Object.values(entry.projects).some((project) =>
        this.io.exists(path.join(project.dir, "results.json")),
      );
      if (alive) this.entries.set(entry.name, entry);
    }
  }

  private save(): void {
    void this.state?.update(KEY, Object.fromEntries(this.entries));
  }

  /** A name no other run has, so a clicked test row identifies exactly one run. */
  newName(): string {
    const base = `${RUN_NAME_PREFIX} ${this.clock().toLocaleString()}`;
    let name = base;
    for (let n = 2; this.entries.has(name); n++) name = `${base} (${n})`;
    this.entries.set(name, { name, at: this.clock().getTime(), projects: {} });
    return name;
  }

  start(name: string, projectKey: string, label: string, dir: string): void {
    const entry = this.entries.get(name) ?? {
      name,
      at: this.clock().getTime(),
      projects: {},
    };
    entry.projects[projectKey] = { label, dir };
    this.entries.set(name, entry);
    this.save();
  }

  finish(
    name: string | undefined,
    projectKey: string,
    counts: { failed: number; passed: number },
  ): void {
    const project = name
      ? this.entries.get(name)?.projects[projectKey]
      : undefined;
    if (!project) return;
    Object.assign(project, counts);
    this.save();
    this.listeners.forEach((listener) => listener());
  }

  get(name: string | undefined): RunEntry | undefined {
    return name ? this.entries.get(name) : undefined;
  }

  /** The report folder of a run; the named project's, or the only (first) one. */
  dirFor(name: string | undefined, projectKey?: string): string | undefined {
    const entry = this.get(name);
    if (!entry) return undefined;
    const project =
      (projectKey && entry.projects[projectKey]) ||
      Object.values(entry.projects)[0];
    return project?.dir;
  }

  /** Runs whose results are still on disk, newest first. */
  list(): RunEntry[] {
    return [...this.entries.values()]
      .filter((entry) =>
        Object.values(entry.projects).some((p) =>
          this.io.exists(path.join(p.dir, "results.json")),
        ),
      )
      .sort((a, b) => b.at - a.at);
  }

  /** Forget a run and delete its report folders, but only ones this extension created under `runs/`. */
  async discard(name: string, projectKeys?: readonly string[]): Promise<void> {
    const previous = this.discards.get(name);
    if (previous) await previous;
    const entry = this.entries.get(name);
    if (!entry) return;
    const removed: RunEntry = { ...entry, projects: {} };
    const operation = (async () => {
      for (const [key, project] of Object.entries(entry.projects)) {
        if (projectKeys && !projectKeys.includes(key)) continue;
        const directory = path.resolve(project.dir);
        if (path.basename(path.dirname(directory)) === "runs")
          await this.io.remove(directory);
        removed.projects[key] = project;
        delete entry.projects[key];
      }
    })();
    this.discards.set(name, operation);
    try {
      await operation;
    } finally {
      this.discards.delete(name);
      if (!Object.keys(entry.projects).length) this.entries.delete(name);
      this.save();
      if (Object.keys(removed.projects).length)
        this.listeners.forEach((listener) => listener(removed));
    }
  }

  /** Keep the newest `keep` runs and discard the rest, so folders cannot pile up. */
  async prune(keep: number): Promise<void> {
    const surplus = [...this.entries.values()]
      .sort((a, b) => b.at - a.at)
      .slice(Math.max(1, keep));
    for (const entry of surplus) await this.discard(entry.name);
  }
}
