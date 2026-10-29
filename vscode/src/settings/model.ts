import * as path from "node:path";
import { parseDocument, isMap, type Document } from "yaml";

export type SettingsScope = "shared" | "local";
export type SettingGroup =
  "Application" | "Test runs" | "Evidence" | "Debugging";
/** What a setting does, worded for each file it can be edited in. */
export interface SettingDescription {
  /** User Settings: wintestkit.local.yaml, this machine only, ignored by Git. */
  user: string;
  /** Repository Settings: wintestkit.yaml, committed and shared with everyone. */
  repository: string;
}
export interface SettingField {
  key: string;
  label: string;
  kind: "string" | "number" | "boolean" | "list" | "select" | "color";
  description: SettingDescription;
  /** An example shown in an empty text box, worded for the file: paths differ between them. */
  placeholder?: SettingDescription;
  default?: unknown;
  choices?: string[];
  localOnly?: boolean;
  /**
   * A decision for the whole repository: it can only be written to wintestkit.yaml, and User Settings
   * show where it stands with a button to Repository Settings instead of a control.
   */
  repositoryOnly?: boolean;
  /** A boolean setting that stays disabled until this other one is on. */
  requires?: string;
  minimum?: number;
  maximum?: number;
  group?: SettingGroup;
}
/** A setting that means the same in both files. */
const same = (text: string): SettingDescription => ({
  user: text,
  repository: text,
});
export const settingFields: SettingField[] = [
  { key: "inspector.enabled", label: "Enable managed inspector", kind: "boolean", description: same("Allow managed inspection of WPF applications."), default: false, group: "Debugging" },
  { key: "inspector.attach", label: "Managed inspector attachment", kind: "select", description: same("Manual attachment or attachment on demand."), default: "manual", choices: ["manual", "on-demand"], group: "Debugging" },
  { key: "inspector.attach_timeout", label: "Inspector attach timeout (seconds)", kind: "number", description: same("Maximum time to wait for attachment, up to 10 seconds."), default: 10, minimum: 0, maximum: 10, group: "Debugging" },
  { key: "inspector.request_timeout", label: "Inspector request timeout (seconds)", kind: "number", description: same("Maximum time to wait for a request, up to 2 seconds."), default: 2, minimum: 0, maximum: 2, group: "Debugging" },
  { key: "inspector.redact_names", label: "Additional redacted names (JSON array)", kind: "list", description: same("Additional sensitive name substrings to redact."), default: [], group: "Debugging" },
  {
    key: "app.path",
    label: "Application executable",
    kind: "string",
    placeholder: {
      user: "C:\\Program Files\\Contoso\\Orders.exe",
      repository: "bin/Debug/Orders.exe",
    },
    description: {
      user: "The .exe to start for tests on this machine.",
      repository:
        "The .exe to start for tests. A path relative to the project folder is recommended.",
    },
    group: "Application",
  },
  {
    key: "app.process",
    label: "Process name",
    kind: "string",
    placeholder: same("Orders.exe"),
    description: {
      user: "Process to find or attach to on this machine.",
      repository: "Process to find or attach to, for example Orders.exe.",
    },
    group: "Application",
  },
  {
    key: "app.args",
    label: "Application arguments (JSON array)",
    kind: "list",
    description: {
      user: 'Arguments for this machine, for example ["--demo"].',
      repository: 'Arguments for everyone, for example ["--demo"].',
    },
    default: [],
    group: "Application",
  },
  {
    key: "app.cwd",
    label: "Working directory",
    kind: "string",
    placeholder: same("C:\\Program Files\\Contoso"),
    description: same("Folder the application starts in."),
    localOnly: true,
    group: "Application",
  },
  {
    key: "launch",
    label: "Application lifecycle",
    kind: "select",
    description: same(
      "Start a fresh app for every test, or attach to a running one.",
    ),
    default: "per-test",
    choices: ["per-test", "attach"],
    group: "Application",
  },
  {
    key: "app.startup_timeout",
    label: "Startup timeout (seconds)",
    kind: "number",
    description: {
      user: "Seconds to wait for the window. Raise it on a slow machine.",
      repository: "Seconds to wait for the application's window to appear.",
    },
    default: 30,
    minimum: 0.001,
    group: "Application",
  },
  {
    key: "app.close_timeout",
    label: "Close timeout (seconds)",
    kind: "number",
    description: {
      user: "Seconds to wait for the app to close. Raise it on a slow machine.",
      repository: "Seconds to wait for the app to close before it is stopped.",
    },
    default: 10,
    minimum: 0.001,
    group: "Application",
  },
  {
    key: "timeout",
    label: "Action / assertion timeout (seconds)",
    kind: "number",
    description: {
      user: "Seconds an action or assertion waits. Raise it on a slow machine.",
      repository: "Seconds an action or assertion waits before it fails.",
    },
    default: 10,
    minimum: 0.001,
    group: "Test runs",
  },
  {
    key: "input_mode",
    label: "Input mode",
    kind: "select",
    description: same("UI Automation patterns or simulated mouse input."),
    default: "pattern",
    choices: ["pattern", "mouse"],
    group: "Test runs",
  },
  {
    key: "screenshots",
    label: "Screenshot policy",
    kind: "select",
    description: same("Never, on failure, or after every step."),
    default: "on-failure",
    choices: ["off", "on-failure", "every-step"],
    group: "Evidence",
  },
  {
    key: "object_previews",
    label: "Save Check Element captures",
    kind: "boolean",
    description: same(
      "Save element and app images when Check exists succeeds. Images may show sensitive data.",
    ),
    default: true,
    group: "Evidence",
  },
  {
    key: "object_previews_share",
    label: "Share Check Element captures in the repository",
    kind: "boolean",
    description: {
      user: "Whether saved captures are committed with the project is decided once for the whole repository, in Repository Settings.",
      repository:
        "Commit saved captures (the object-previews folder) so everyone sees them. Off keeps them on each machine and ignored by Git. Images may show sensitive data.",
    },
    default: false,
    repositoryOnly: true,
    requires: "object_previews",
    group: "Evidence",
  },
  {
    key: "replay",
    label: "Test replay recording",
    kind: "select",
    description: same("Record screenshots for playback in the report."),
    default: "off",
    choices: ["off", "on", "retain-on-failure"],
    group: "Evidence",
  },
  {
    key: "replay_fps",
    label: "Replay capture rate (FPS)",
    kind: "number",
    description: same("Frames per second recorded for replays."),
    default: 15,
    minimum: 0,
    maximum: 30,
    group: "Evidence",
  },
  {
    key: "replay_scope",
    label: "Replay capture scope",
    kind: "select",
    description: same("Record the app window or the whole desktop."),
    default: "window",
    choices: ["window", "desktop"],
    group: "Evidence",
  },
  {
    key: "report_dir",
    label: "Report directory",
    kind: "string",
    description: same("Folder for the HTML report and its images."),
    default: "wtk-report",
    group: "Test runs",
  },
  {
    key: "python_paths",
    label: "Python import paths (JSON array)",
    kind: "list",
    description: same("Folders added to Python's import path."),
    default: ["."],
    group: "Test runs",
  },
  {
    key: "highlight_actions",
    label: "Flash elements during test runs",
    kind: "boolean",
    description: same("Flash each element before a test acts on it."),
    default: false,
    localOnly: true,
    group: "Debugging",
  },
  {
    key: "highlight_color",
    label: "Highlight color",
    kind: "color",
    description: same("Outline color for flashes, highlights and Spy."),
    default: "#FF0000",
    localOnly: true,
    group: "Debugging",
  },
  {
    key: "slow_mo_ms",
    label: "Slow motion (milliseconds)",
    kind: "number",
    description: same("Pause after each action to follow runs easily."),
    default: 0,
    minimum: 0,
    localOnly: true,
    group: "Debugging",
  },
];

export interface SettingSection {
  group: SettingGroup;
  fields: SettingField[];
}

export function settingSections(scope: SettingsScope): SettingSection[] {
  const editable = settingFields.filter(
    (field) => scope === "local" || !field.localOnly,
  );
  const groups: SettingGroup[] = [
    "Application",
    "Test runs",
    "Evidence",
    "Debugging",
  ];
  return groups
    .map((group) => ({
      group,
      fields: editable.filter((field) => field.group === group),
    }))
    .filter((section) => section.fields.length);
}

export function settingsScope(filename: string): SettingsScope {
  return filename.endsWith("wintestkit.local.yaml") ? "local" : "shared";
}

export function parseSettings(source: string) {
  const document = parseDocument(source, { version: "1.1", uniqueKeys: true });
  if (document.errors.length) throw new Error(document.errors[0].message);
  if (document.contents !== null && !isMap(document.contents))
    throw new Error("Configuration must be a YAML mapping.");
  const value: unknown = document.toJS({ maxAliasCount: 50 }) ?? {};
  validateSettings(value);
  return document;
}

export function flattenSettings(
  value: Record<string, unknown>,
): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (
      (key === "app" || key === "inspector") &&
      entry &&
      typeof entry === "object" &&
      !Array.isArray(entry)
    )
      for (const [name, setting] of Object.entries(entry))
        flat[key + "." + name] = setting;
    else flat[key] = entry;
  }
  return flat;
}

/**
 * The path as stored in the repository file: relative to the project folder, with forward slashes,
 * when the file is inside it. A file elsewhere is stored as the absolute path, which the page warns
 * about because it only works where the file is in the same place.
 */
export function repositoryPath(root: string, file: string): string {
  const relative = path.relative(root, file);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative))
    return file;
  return relative.split(path.sep).join("/");
}

/** Drive, UNC and rooted paths only make sense on one machine. */
export function isMachinePath(value: string): boolean {
  return /^(?:[a-zA-Z]:|[\\/])/.test(value);
}

export function validateSettings(
  value: unknown,
): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Configuration must be a mapping.");
  const config = value as Record<string, unknown>;
  if (
    config.app !== undefined &&
    (!config.app || Object.getPrototypeOf(config.app) !== Object.prototype)
  )
    throw new Error("app must be a mapping.");
  if (config.inspector !== undefined && (!config.inspector || Object.getPrototypeOf(config.inspector) !== Object.prototype))
    throw new Error("inspector must be a mapping.");
  const flat = flattenSettings(config);
  for (const [key, entry] of Object.entries(flat)) {
    if (key === "app.env") {
      if (
        !entry ||
        typeof entry !== "object" ||
        Object.getPrototypeOf(entry) !== Object.prototype ||
        Object.values(entry).some((item) => typeof item !== "string")
      )
        throw new Error("app.env must map names to strings.");
      continue;
    }
    const field = settingFields.find((field) => field.key === key);
    if (!field) throw new Error("Unknown setting: " + key);
    if (field.kind === "boolean" && typeof entry !== "boolean")
      throw new Error(key + " must be true or false.");
    if (
      field.kind === "number" &&
      (typeof entry !== "number" ||
        !Number.isFinite(entry) ||
        entry < (field.minimum ?? 0) ||
        (key === "replay_fps" && entry <= 0) ||
        ((key === "inspector.attach_timeout" || key === "inspector.request_timeout") && entry <= 0) ||
        (field.maximum !== undefined && entry > field.maximum) ||
        (key === "slow_mo_ms" && !Number.isInteger(entry)))
    )
      throw new Error(
        key +
          " must be a valid " +
          (key === "slow_mo_ms" ? "whole number" : "positive number") +
          ".",
      );
    if (
      (field.kind === "string" || field.kind === "select") &&
      (typeof entry !== "string" || !entry.length)
    )
      throw new Error(key + " must be a non-empty string.");
    if (field.kind === "select" && !field.choices?.includes(entry as string))
      throw new Error("Invalid " + key);
    if (
      field.kind === "color" &&
      (typeof entry !== "string" || !/^#[0-9a-fA-F]{6}$/.test(entry))
    )
      throw new Error(key + " must be a #RRGGBB colour.");
    if (
      field.kind === "list" &&
      (!Array.isArray(entry) || entry.some((item) => typeof item !== "string" || (key === "inspector.redact_names" && !item.length)))
    )
      throw new Error(key + " must be a JSON array of strings.");
  }
}

export function updateSetting(
  source: string,
  scope: SettingsScope,
  key: string,
  value: unknown,
  remove: boolean,
): string {
  const field = settingFields.find((field) => field.key === key);
  if (!field || (scope === "shared" && field.localOnly))
    throw new Error("Edit this setting in local machine settings.");
  if (scope === "local" && field.repositoryOnly)
    throw new Error("Edit this setting in Repository Settings.");
  const document: Document = parseSettings(source);
  if (document.contents === null) document.contents = document.createNode({});
  const parent = key.split(".")[0];
  if (!remove && key.includes(".") && !document.has(parent))
    document.set(parent, document.createNode({}));
  if (remove) document.deleteIn(key.split("."));
  else document.setIn(key.split("."), value);
  if (
    isMap(document.get("app", true)) &&
    (document.get("app", true) as { items: unknown[] }).items.length === 0
  )
    document.delete("app");
  if (isMap(document.get("inspector", true)) && (document.get("inspector", true) as { items: unknown[] }).items.length === 0)
    document.delete("inspector");
  validateSettings(document.toJS({ maxAliasCount: 50 }));
  return document.toString();
}
