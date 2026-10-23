import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  flattenSettings,
  parseSettings,
  projectRelativePath,
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
  it("allows a project-relative executable and arguments in the repository file", () => {
    const source = updateSetting("{}", "shared", "app.path", "bin/Debug/App.exe", false);
    expect(parseSettings(source, "shared").toJS()).toEqual({
      app: { path: "bin/Debug/App.exe" },
    });
    const withArgs = updateSetting(source, "shared", "app.args", ["--test-mode"], false);
    expect(parseSettings(withArgs, "shared").toJS()).toEqual({
      app: { path: "bin/Debug/App.exe", args: ["--test-mode"] },
    });
    for (const absolute of ["C:/App.exe", "C:\\Apps\\App.exe", "\\\\host\\share\\App.exe", "/App.exe"])
      expect(() =>
        updateSetting("{}", "shared", "app.path", absolute, false),
      ).toThrow(/relative to the project folder/);
  });
  it("stores a browsed executable relative to the project, and only inside it", () => {
    const root = path.resolve("project");
    expect(projectRelativePath(root, path.join(root, "bin", "Debug", "App.exe"))).toBe(
      "bin/Debug/App.exe",
    );
    expect(() => projectRelativePath(root, path.resolve("elsewhere", "App.exe"))).toThrow(
      /inside the project folder/,
    );
    expect(() => projectRelativePath(root, root)).toThrow(/inside the project folder/);
  });
  it("keeps absolute executable paths and personal controls in User Settings", () => {
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
    "app:\n  path: C:/App.exe",
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
  it("lists every local setting, starting with the executable path under Application", () => {
    const local = settingSections("local");
    expect(local[0].fields[0].key).toBe("app.path");
    expect(local.map((section) => section.group)).toEqual([
      "Application",
      "Test runs",
      "Evidence",
      "Debugging",
    ]);
    const keys = local
      .flatMap((section) => section.fields)
      .map((field) => field.key);
    expect(keys.sort()).toEqual(settingFields.map((field) => field.key).sort());
  });
  it("describes every setting for both User and Repository Settings", () => {
    for (const field of settingFields) {
      expect(field.description.user.trim(), field.key).not.toBe("");
      expect(field.description.repository.trim(), field.key).not.toBe("");
    }
    // Where the file matters, the text says which one it is for.
    const path = settingFields.find((field) => field.key === "app.path")?.description;
    expect(path?.user).not.toBe(path?.repository);
  });
  it("groups evidence controls separately and bounds replay FPS like the backend", () => {
    const evidence = settingSections("shared").find((group) => group.group === "Evidence");
    expect(evidence?.fields.map((field) => field.key)).toEqual([
      "screenshots", "object_previews", "replay", "replay_fps", "replay_scope",
    ]);
    expect(settingFields.find((field) => field.key === "replay_fps")).toMatchObject({ minimum: 0, maximum: 30 });
    for (const fps of [0, -1, 30.01])
      expect(() => updateSetting("{}", "shared", "replay_fps", fps, false)).toThrow();
    expect(() => updateSetting("{}", "shared", "replay_fps", 30, false)).not.toThrow();
  });
  it("allows portable object previews to be disabled in shared or local settings", () => {
    for (const scope of ["shared", "local"] as const) {
      const source = updateSetting("{}", scope, "object_previews", false, false);
      expect(parseSettings(source, scope).toJS()).toEqual({ object_previews: false });
      expect(() =>
        updateSetting(source, scope, "object_previews", "false", false),
      ).toThrow(/true or false/);
    }
    expect(settingFields.find((field) => field.key === "object_previews")).toMatchObject({
      kind: "boolean",
      default: true,
      group: "Evidence",
    });
  });
  it("keeps machine-only options out of shared sections", () => {
    const shared = settingSections("shared");
    const keys = shared.flatMap((section) =>
      section.fields.map((field) => field.key),
    );
    expect(keys).toContain("timeout");
    expect(keys).toContain("app.process");
    expect(keys).toContain("app.path");
    expect(keys).toContain("app.args");
    expect(keys).not.toContain("app.cwd");
    for (const field of settingFields.filter((field) => field.localOnly))
      expect(keys).not.toContain(field.key);
    expect(shared.map((section) => section.group)).not.toContain(
      "Debugging",
    );
  });
  it("distinguishes shared and ignored local files", () => {
    expect(settingsScope("/project/wintestkit.local.yaml")).toBe("local");
    expect(settingsScope("/project/wintestkit.yaml")).toBe("shared");
  });
  it("stores the highlight color as a quoted #RRGGBB value in User Settings only", () => {
    const source = updateSetting("{}", "local", "highlight_color", "#1E90FF", false);
    expect(parseSettings(source, "local").toJS()).toEqual({ highlight_color: "#1E90FF" });
    expect(source).toMatch(/highlight_color: ["']#1E90FF["']/);
    for (const bad of ["red", "#FFF", "1E90FF", "#GG0000", 16711680])
      expect(() => updateSetting("{}", "local", "highlight_color", bad, false)).toThrow(
        /#RRGGBB/,
      );
    expect(() => updateSetting("{}", "shared", "highlight_color", "#1E90FF", false)).toThrow(
      /local/,
    );
    expect(settingFields.find((field) => field.key === "highlight_color")).toMatchObject({
      kind: "color",
      default: "#FF0000",
      group: "Debugging",
    });
  });
});
