import { describe, expect, it } from "vitest";
import {
  flattenSettings,
  parseSettings,
  settingFields,
  settingSections,
  settingsScope,
  updateSetting,
} from "../../src/settings/model";

describe("YAML configuration editing", () => {
  it("preserves comments and unrelated fields while changing a setting", () => {
    const source =
      "# My settings\ntimeout: 10 # Keep this note\napp:\n  process: App.exe\n";
    const edited = updateSetting(source, "shared", "timeout", 25, false);
    expect(edited).toContain("# My settings");
    expect(edited).toContain("# Keep this note");
    expect(parseSettings(edited, "shared").toJS()).toEqual({
      timeout: 25,
      app: { process: "App.exe" },
    });
  });
  it("keeps executable paths and personal controls local", () => {
    expect(() =>
      updateSetting("{}", "shared", "app.path", "C:/App.exe", false),
    ).toThrow(/local/);
    expect(() =>
      updateSetting("{}", "shared", "slow_mo_ms", 100, false),
    ).toThrow(/local/);
    const source = updateSetting(
      "{}",
      "local",
      "app.path",
      "C:\\Apps\\App.exe",
      false,
    );
    expect(
      flattenSettings(parseSettings(source, "local").toJS())["app.path"],
    ).toBe("C:\\Apps\\App.exe");
    expect(
      parseSettings(
        updateSetting(source, "local", "app.path", null, true),
        "local",
      ).toJS(),
    ).toEqual({});
  });
  it.each([
    "timeout: [",
    "timeout: 1\ntimeout: 2",
    "- nope",
    "timeout: .inf",
    "app: nope",
    "app: !!omap []",
    "app:\n  env: !!omap []",
    "app:\n  path: App.exe",
    "foo: true",
  ])("rejects invalid shared YAML: %s", (source) => {
    expect(() => parseSettings(source, "shared")).toThrow();
  });
  it.each([
    ["timeout", 0],
    ["timeout", -1],
    ["slow_mo_ms", 1.5],
    ["highlight_actions", "yes"],
    ["launch", "invalid"],
    ["python_paths", [3]],
    ["app.env", { TOKEN: 123 }],
  ])("validates %s", (key, value) => {
    const source = key.startsWith("app.") ? "app:\n  env: {}\n" : "{}";
    if (key === "app.env")
      expect(() =>
        parseSettings("app:\n  env:\n    TOKEN: 123", "local"),
      ).toThrow();
    else
      expect(() =>
        updateSetting(source, "local", key as string, value, false),
      ).toThrow();
  });
  it("edits an empty YAML document as an ordinary mapping", () => {
    const source = updateSetting("", "local", "app.path", "C:/App.exe", false);
    expect(parseSettings(source, "local").toJS()).toEqual({
      app: { path: "C:/App.exe" },
    });
    expect(
      parseSettings(
        updateSetting("", "shared", "timeout", 15, false),
        "shared",
      ).toJS(),
    ).toEqual({ timeout: 15 });
  });
  it("shows only the executable path as a local app-start essential", () => {
    const local = settingSections("local");
    expect(local.essentials.map((field) => field.key)).toEqual(["app.path"]);
    expect(local.advanced.map((section) => section.group)).toEqual([
      "Application",
      "Test runs",
      "Evidence",
      "Debugging",
    ]);
    const keys = [
      ...local.essentials,
      ...local.advanced.flatMap((section) => section.fields),
    ].map((field) => field.key);
    expect(keys.sort()).toEqual(settingFields.map((field) => field.key).sort());
  });
  it("groups evidence controls separately and bounds trace FPS like the backend", () => {
    const evidence = settingSections("shared").advanced.find((group) => group.group === "Evidence");
    expect(evidence?.fields.map((field) => field.key)).toEqual([
      "screenshots", "trace", "trace_fps", "trace_scope",
    ]);
    expect(settingFields.find((field) => field.key === "trace_fps")).toMatchObject({ minimum: 0, maximum: 30 });
    for (const fps of [0, -1, 30.01])
      expect(() => updateSetting("{}", "shared", "trace_fps", fps, false)).toThrow();
    expect(() => updateSetting("{}", "shared", "trace_fps", 30, false)).not.toThrow();
  });
  it("keeps machine-only options out of shared sections", () => {
    const shared = settingSections("shared");
    expect(shared.essentials).toEqual([]);
    const keys = shared.advanced.flatMap((section) =>
      section.fields.map((field) => field.key),
    );
    expect(keys).toContain("timeout");
    expect(keys).toContain("app.process");
    for (const field of settingFields.filter((field) => field.localOnly))
      expect(keys).not.toContain(field.key);
    expect(shared.advanced.map((section) => section.group)).not.toContain(
      "Debugging",
    );
  });
  it("distinguishes shared and ignored local files", () => {
    expect(settingsScope("/project/wintestkit.local.yaml")).toBe("local");
    expect(settingsScope("/project/wintestkit.yaml")).toBe("shared");
  });
});
