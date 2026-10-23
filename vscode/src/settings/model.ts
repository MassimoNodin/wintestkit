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
  {
    key: "app.path",
    label: "Application executable",
    kind: "string",
    placeholder: {
      user: "C:\\Program Files\\Contoso\\Orders.exe",
      repository: "bin/Debug/Orders.exe",
    },
    description: {
      user: "The .exe WinTestKit starts for tests on this machine. Use an absolute path; it takes precedence over the repository's executable.",
      repository:
        "The .exe WinTestKit starts for tests, shared with everyone who uses this repository. Use a path relative to the project folder; set an absolute path in User Settings instead.",
    },
    group: "Application",
  },
  {
    key: "app.process",
    label: "Process name",
    kind: "string",
    placeholder: same("Orders.exe"),
    description: {
      user: "Finds or attaches to an application that is already running on this machine. Takes precedence over the repository's process name.",
      repository:
        "Finds or attaches to an application that is already running, for everyone who uses this repository. Use the exe name, for example Orders.exe.",
    },
    group: "Application",
  },
  {
    key: "app.args",
    label: "Application arguments (JSON array)",
    kind: "list",
    description: {
      user: `Command-line arguments for the application on this machine, for example ["--demo"]. They replace the repository's arguments.`,
      repository:
        'Command-line arguments the application starts with for everyone who uses this repository, for example ["--demo"].',
    },
    default: [],
    group: "Application",
  },
  {
    key: "app.cwd",
    label: "Working directory",
    kind: "string",
    placeholder: same("C:\\Program Files\\Contoso"),
    description: same(
      "Folder the application starts in on this machine. Only available in User Settings, because folders differ between machines.",
    ),
    localOnly: true,
    group: "Application",
  },
  {
    key: "launch",
    label: "Application lifecycle",
    kind: "select",
    description: {
      user: "Start a fresh app for every test, or attach to one that is already running, on this machine. Overrides the repository's choice.",
      repository:
        "Start a fresh app for every test, or attach to a running app, as the default for everyone who uses this repository.",
    },
    default: "per-test",
    choices: ["per-test", "attach"],
    group: "Application",
  },
  {
    key: "app.startup_timeout",
    label: "Startup timeout (seconds)",
    kind: "number",
    description: {
      user: "How long to wait for the application's window to appear after it starts. Raise it if this machine is slow.",
      repository:
        "How long to wait for the application's window to appear after it starts, for everyone who uses this repository.",
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
      user: "How long to wait for the application to close before it is stopped. Raise it if this machine is slow.",
      repository:
        "How long to wait for the application to close before it is stopped, for everyone who uses this repository.",
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
      user: "How long an action or assertion waits for its element before it fails. Raise it if this machine is slow.",
      repository:
        "How long an action or assertion waits for its element before it fails, for everyone who uses this repository.",
    },
    default: 10,
    minimum: 0.001,
    group: "Test runs",
  },
  {
    key: "input_mode",
    label: "Input mode",
    kind: "select",
    description: same("Use UI Automation patterns or simulated mouse input."),
    default: "pattern",
    choices: ["pattern", "mouse"],
    group: "Test runs",
  },
  {
    key: "screenshots",
    label: "Screenshot policy",
    kind: "select",
    description: same(
      "When screenshots are saved: never, only when a test fails, or after every step.",
    ),
    default: "on-failure",
    choices: ["off", "on-failure", "every-step"],
    group: "Evidence",
  },
  {
    key: "object_previews",
    label: "Save last-successful element images",
    kind: "boolean",
    description: same(
      "Save an element crop and a red-outlined app image with the project. Both may contain sensitive information.",
    ),
    default: true,
    group: "Evidence",
  },
  {
    key: "replay",
    label: "Test replay recording",
    kind: "select",
    description: same("Capture screenshots for playback in the HTML report."),
    default: "off",
    choices: ["off", "on", "retain-on-failure"],
    group: "Evidence",
  },
  {
    key: "replay_fps",
    label: "Replay capture rate (FPS)",
    kind: "number",
    description: same(
      "Frames captured per second while a replay is recorded. Higher is smoother but makes larger reports.",
    ),
    default: 15,
    minimum: 0,
    maximum: 30,
    group: "Evidence",
  },
  {
    key: "replay_scope",
    label: "Replay capture scope",
    kind: "select",
    description: same(
      "Record only the application window, or the whole desktop.",
    ),
    default: "window",
    choices: ["window", "desktop"],
    group: "Evidence",
  },
  {
    key: "report_dir",
    label: "Report directory",
    kind: "string",
    description: same(
      "Folder the HTML report, screenshots and replay frames are written to.",
    ),
    default: "wtk-report",
    group: "Test runs",
  },
  {
    key: "python_paths",
    label: "Python import paths (JSON array)",
    kind: "list",
    description: same(
      'Folders added to Python\'s import path so tests can import your own modules, for example ["."].',
    ),
    default: ["."],
    group: "Test runs",
  },
  {
    key: "highlight_actions",
    label: "Flash elements during test runs",
    kind: "boolean",
    description: same(
      "Flash each element just before a test acts on it. Spy's Highlight is separate and only outlines an element you select.",
    ),
    default: false,
    localOnly: true,
    group: "Debugging",
  },
  {
    key: "highlight_color",
    label: "Highlight color",
    kind: "color",
    description: same(
      "The outline color used whenever WinTestKit highlights an element: flashes during test runs, Spy and the highlight commands.",
    ),
    default: "#FF0000",
    localOnly: true,
    group: "Debugging",
  },
  {
    key: "slow_mo_ms",
    label: "Slow motion (milliseconds)",
    kind: "number",
    description: same("Pause after each action so runs are easier to follow."),
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

export function parseSettings(source: string, scope: SettingsScope) {
  const document = parseDocument(source, { version: "1.1", uniqueKeys: true });
  if (document.errors.length) throw new Error(document.errors[0].message);
  if (document.contents !== null && !isMap(document.contents))
    throw new Error("Configuration must be a YAML mapping.");
  const value: unknown = document.toJS({ maxAliasCount: 50 }) ?? {};
  validateSettings(value, scope);
  return document;
}

export function flattenSettings(
  value: Record<string, unknown>,
): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (
      key === "app" &&
      entry &&
      typeof entry === "object" &&
      !Array.isArray(entry)
    )
      for (const [name, setting] of Object.entries(entry))
        flat["app." + name] = setting;
    else flat[key] = entry;
  }
  return flat;
}

/** The path as stored in the repository file: relative to the project folder, with forward slashes. */
export function projectRelativePath(root: string, file: string): string {
  const relative = path.relative(root, file);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative))
    throw new Error(
      "Choose an executable inside the project folder, or set an absolute path in User Settings.",
    );
  return relative.split(path.sep).join("/");
}

/** Drive, UNC and rooted paths only make sense on one machine. */
export function isMachinePath(value: string): boolean {
  return /^(?:[a-zA-Z]:|[\\/])/.test(value);
}

export function validateSettings(
  value: unknown,
  scope: SettingsScope,
): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Configuration must be a mapping.");
  const config = value as Record<string, unknown>;
  if (
    config.app !== undefined &&
    (!config.app || Object.getPrototypeOf(config.app) !== Object.prototype)
  )
    throw new Error("app must be a mapping.");
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
    if (
      key === "app.path" &&
      scope === "shared" &&
      typeof entry === "string" &&
      isMachinePath(entry)
    )
      throw new Error(
        "Use a path relative to the project folder in Repository Settings; absolute paths belong in User Settings.",
      );
    if (field.kind === "boolean" && typeof entry !== "boolean")
      throw new Error(key + " must be true or false.");
    if (
      field.kind === "number" &&
      (typeof entry !== "number" ||
        !Number.isFinite(entry) ||
        entry < (field.minimum ?? 0) ||
        (key === "replay_fps" && entry <= 0) ||
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
      (!Array.isArray(entry) || entry.some((item) => typeof item !== "string"))
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
  const document: Document = parseSettings(source, scope);
  if (document.contents === null) document.contents = document.createNode({});
  if (!remove && key.startsWith("app.") && !document.has("app"))
    document.set("app", document.createNode({}));
  if (remove) document.deleteIn(key.split("."));
  else document.setIn(key.split("."), value);
  if (
    isMap(document.get("app", true)) &&
    (document.get("app", true) as { items: unknown[] }).items.length === 0
  )
    document.delete("app");
  validateSettings(document.toJS({ maxAliasCount: 50 }), scope);
  return document.toString();
}
