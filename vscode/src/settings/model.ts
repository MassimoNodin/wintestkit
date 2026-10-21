import { parseDocument, isMap, type Document } from "yaml";

export type SettingsScope = "shared" | "local";
export type SettingGroup = "Application" | "Test runs" | "Evidence" | "Debugging";
export interface SettingField {
  key: string;
  label: string;
  kind: "string" | "number" | "boolean" | "list" | "select";
  description?: string;
  default?: unknown;
  choices?: string[];
  localOnly?: boolean;
  minimum?: number;
  maximum?: number;
  group?: SettingGroup;
}
export const settingFields: SettingField[] = [
  {
    key: "app.path",
    label: "Application executable",
    kind: "string",
    description:
      "The .exe WinTestKit starts for tests. Stored only on this machine.",
    localOnly: true,
  },
  {
    key: "app.process",
    label: "Process name",
    kind: "string",
    description: "Finds or attaches to an application that is already running.",
    group: "Application",
  },
  {
    key: "app.args",
    label: "Application arguments (JSON array)",
    kind: "list",
    description: 'Command-line arguments, for example ["--demo"].',
    default: [],
    localOnly: true,
    group: "Application",
  },
  {
    key: "app.cwd",
    label: "Working directory",
    kind: "string",
    description: "Folder the application starts in.",
    localOnly: true,
    group: "Application",
  },
  {
    key: "launch",
    label: "Application lifecycle",
    kind: "select",
    description:
      "Start a fresh app for every test, or attach to a running app.",
    default: "per-test",
    choices: ["per-test", "attach"],
    group: "Application",
  },
  {
    key: "app.startup_timeout",
    label: "Startup timeout (seconds)",
    kind: "number",
    default: 30,
    minimum: 0.001,
    group: "Application",
  },
  {
    key: "app.close_timeout",
    label: "Close timeout (seconds)",
    kind: "number",
    default: 10,
    minimum: 0.001,
    group: "Application",
  },
  {
    key: "timeout",
    label: "Action / assertion timeout (seconds)",
    kind: "number",
    default: 10,
    minimum: 0.001,
    group: "Test runs",
  },
  {
    key: "input_mode",
    label: "Input mode",
    kind: "select",
    description: "Use UI Automation patterns or simulated mouse input.",
    default: "pattern",
    choices: ["pattern", "mouse"],
    group: "Test runs",
  },
  {
    key: "screenshots",
    label: "Screenshot policy",
    kind: "select",
    default: "on-failure",
    choices: ["off", "on-failure", "every-step"],
    group: "Evidence",
  },
  {
    key: "object_previews",
    label: "Save last-successful element images",
    kind: "boolean",
    description:
      "Save an element crop and a red-outlined app image with the project. Both may contain sensitive information.",
    default: true,
    group: "Evidence",
  },
  {
    key: "replay",
    label: "Test replay recording",
    kind: "select",
    description: "Capture screenshots for playback in the HTML report.",
    default: "off",
    choices: ["off", "on", "retain-on-failure"],
    group: "Evidence",
  },
  {
    key: "replay_fps",
    label: "Replay capture rate (FPS)",
    kind: "number",
    default: 15,
    minimum: 0,
    maximum: 30,
    group: "Evidence",
  },
  {
    key: "replay_scope",
    label: "Replay capture scope",
    kind: "select",
    default: "window",
    choices: ["window", "desktop"],
    group: "Evidence",
  },
  {
    key: "report_dir",
    label: "Report directory",
    kind: "string",
    default: "wtk-report",
    group: "Test runs",
  },
  {
    key: "python_paths",
    label: "Python import paths (JSON array)",
    kind: "list",
    default: ["."],
    group: "Test runs",
  },
  {
    key: "highlight_actions",
    label: "Highlight actions",
    kind: "boolean",
    description: "Flash each element before WinTestKit acts on it.",
    default: false,
    localOnly: true,
    group: "Debugging",
  },
  {
    key: "slow_mo_ms",
    label: "Slow motion (milliseconds)",
    kind: "number",
    description: "Pause after each action so runs are easier to follow.",
    default: 0,
    minimum: 0,
    localOnly: true,
    group: "Debugging",
  },
];

export interface SettingSections {
  essentials: SettingField[];
  advanced: { group: SettingGroup; fields: SettingField[] }[];
}

export function settingSections(scope: SettingsScope): SettingSections {
  const editable = settingFields.filter(
    (field) => scope === "local" || !field.localOnly,
  );
  const groups: SettingGroup[] = ["Application", "Test runs", "Evidence", "Debugging"];
  return {
    essentials: editable.filter((field) => !field.group),
    advanced: groups
      .map((group) => ({
        group,
        fields: editable.filter((field) => field.group === group),
      }))
      .filter((section) => section.fields.length),
  };
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
    if (key === "app.path" && scope === "shared")
      throw new Error(
        "Application paths belong in ignored wintestkit.local.yaml.",
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
