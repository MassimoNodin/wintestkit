import * as vscode from "vscode";
import type { AppProcessesResult } from "../protocol/generated";
import { readApplicationIcons, readApplicationPaths } from "../spy/appIcons";

type RunningProcess = AppProcessesResult["processes"][number];

/** A row of the picker; `process` is the name saved as `app.process`, absent on separators. */
export type RunningAppItem = vscode.QuickPickItem & { process?: string };

function row(
  entry: RunningProcess,
  icons: Record<string, string>,
  current = false,
): RunningAppItem {
  const id =
    entry.pids.length > 1
      ? entry.pids.length + " processes"
      : "PID " + entry.pids[0];
  const icon = entry.pids.map((pid) => icons[String(pid)]).find(Boolean);
  return {
    // The window title is what people recognise; the process name is what is saved.
    label: entry.windowTitle || entry.name,
    description:
      (entry.windowTitle ? entry.name + "  ·  " + id : id) +
      (current ? "  ·  currently selected" : ""),
    iconPath: icon ? vscode.Uri.parse(icon) : new vscode.ThemeIcon("window"),
    process: entry.name,
  };
}

/**
 * The application the settings already point at, if it is running, then applications that have
 * a window, then background processes, each under a heading. `current` holds the process names
 * the settings refer to (case-insensitive).
 */
export function runningAppItems(
  processes: RunningProcess[],
  icons: Record<string, string> = {},
  current: string[] = [],
): RunningAppItem[] {
  const selected = new Set(current.map((name) => name.toLowerCase()));
  const isCurrent = (entry: RunningProcess) =>
    selected.has(entry.name.toLowerCase());
  const others = processes.filter((entry) => !isCurrent(entry));
  const group = (
    label: string,
    entries: RunningProcess[],
    isSelected = false,
  ): RunningAppItem[] =>
    entries.length
      ? [
          { label, kind: vscode.QuickPickItemKind.Separator },
          ...entries.map((entry) => row(entry, icons, isSelected)),
        ]
      : [];
  return [
    ...group("Current application", processes.filter(isCurrent), true),
    ...group(
      "Windows",
      others.filter((entry) => entry.windowTitle),
    ),
    ...group(
      "Background processes",
      others.filter((entry) => !entry.windowTitle),
    ),
  ];
}

/** The application the user chose: the process name, and its executable when it can be read. */
export interface RunningChoice {
  process: string;
  path?: string;
}

/**
 * Lets the user pick one of the running applications. The list appears at once with a generic
 * icon; the real icons are read in one batch and swapped in when they arrive.
 */
export function pickRunningApplication(
  processes: RunningProcess[],
  current: string[] = [],
): Promise<RunningChoice | undefined> {
  const pick = vscode.window.createQuickPick<RunningAppItem>();
  pick.placeholder = "Select a running app";
  pick.matchOnDescription = true;
  pick.matchOnDetail = true;
  pick.items = runningAppItems(processes, {}, current);
  pick.busy = true;
  return new Promise((resolve) => {
    let finished = false;
    const finish = (name: string | undefined) => {
      if (finished) return;
      finished = true;
      pick.dispose();
      if (name === undefined) return resolve(undefined);
      // An elevated process cannot be read; the choice is then the process name alone.
      const pids = processes.find((entry) => entry.name === name)?.pids ?? [];
      readApplicationPaths(pids)
        .then((paths) =>
          resolve({
            process: name,
            path: pids.map((pid) => paths[String(pid)]).find(Boolean),
          }),
        )
        .catch(() => resolve({ process: name }));
    };
    pick.onDidAccept(() => finish(pick.selectedItems[0]?.process));
    pick.onDidHide(() => finish(undefined));
    pick.show();
    void readApplicationIcons(processes.flatMap((entry) => entry.pids))
      .then((icons) => {
        if (finished) return;
        const active = pick.activeItems[0]?.process;
        pick.items = runningAppItems(processes, icons, current);
        const same = pick.items.find((item) => item.process === active);
        if (same) pick.activeItems = [same];
      })
      .catch(() => undefined)
      .finally(() => {
        if (!finished) pick.busy = false;
      });
  });
}
