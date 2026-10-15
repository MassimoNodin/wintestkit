import { describe, expect, it } from "vitest";
import {
  flattenSettings,
  parseSettings,
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
  it("distinguishes shared and ignored local files", () => {
    expect(settingsScope("/project/wintestkit.local.yaml")).toBe("local");
    expect(settingsScope("/project/wintestkit.yaml")).toBe("shared");
  });
});
