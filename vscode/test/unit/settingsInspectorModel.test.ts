import { describe, expect, it } from "vitest";
import { flattenSettings, parseSettings, settingFields, updateSetting, validateSettings } from "../../src/settings/model";

describe("inspector settings", () => {
  it("exposes all five keys in both scopes", () => {
    for (const key of ["enabled", "attach", "attach_timeout", "request_timeout", "redact_names"]) {
      const field = settingFields.find((item) => item.key === `inspector.${key}`);
      expect(field).toBeDefined(); expect(field?.localOnly).not.toBe(true); expect(field?.repositoryOnly).not.toBe(true);
    }
    for (const scope of ["shared", "local"] as const) expect(updateSetting("", scope, "inspector.enabled", true, false)).toContain("enabled: true");
  });
  it("exposes Python backend and inspector defaults", () => {
    for (const [key, value] of [["backend", "auto"], ["input_mode", "mouse"], ["inspector.enabled", true], ["inspector.attach", "on-launch"]] as const) {
      expect(settingFields.find((field) => field.key === key)?.default).toBe(value);
    }
    expect(settingFields.find((field) => field.key === "backend")?.choices).toEqual(["auto", "uia"]);
    for (const scope of ["shared", "local"] as const) {
      for (const backend of ["auto", "uia"]) expect(updateSetting("", scope, "backend", backend, false)).toContain(`backend: ${backend}`);
      expect(() => updateSetting("", scope, "backend", "other", false)).toThrow();
    }
  });
  it("exposes a repository-only, empty-by-default write allowlist", () => {
    const field = settingFields.find((item) => item.key === "inspector.writes.allow");
    expect(field).toMatchObject({ kind: "list", default: [], repositoryOnly: true, group: "Debugging" });
    expect(field?.description.repository).toContain("exact runtime type");
    expect(field?.description.repository).toContain("empty list denies all writes");
    expect(() => updateSetting("", "local", "inspector.writes.allow", [], false)).toThrow("Repository Settings");
  });
  it("round-trips nested write permissions without losing other inspector settings", () => {
    const entries = ["Example.View.Title", "Example.View.Update(System.String,System.Int64)"];
    const edited = updateSetting("inspector:\n  enabled: true\n", "shared", "inspector.writes.allow", entries, false);
    const parsed = parseSettings(edited).toJS();
    expect(parsed).toEqual({ inspector: { enabled: true, writes: { allow: entries } } });
    expect(flattenSettings(parsed)["inspector.writes.allow"]).toEqual(entries);
    expect(parseSettings(updateSetting(edited, "shared", "inspector.writes.allow", null, true)).toJS()).toEqual({ inspector: { enabled: true } });
    expect(() => validateSettings({ inspector: { writes: { allow: [1] } } })).toThrow("JSON array of strings");
    expect(() => validateSettings({ inspector: { writes: { other: [] } } })).toThrow("Unknown setting");
  });
  it("validates types, bounds and messages", () => {
    validateSettings({ inspector: { enabled: true, attach: "on-demand", attach_timeout: 10, request_timeout: 2, redact_names: ["x".repeat(128)] } });
    for (const [key, value, message] of [["enabled", 1, "true or false"], ["attach", "auto", "Invalid"], ["attach_timeout", 0, "positive number"], ["attach_timeout", 10.1, "positive number"], ["request_timeout", 0, "positive number"], ["request_timeout", 2.1, "positive number"], ["redact_names", [""], "at most 32"], ["redact_names", ["x".repeat(129)], "128 characters"], ["redact_names", Array(33).fill("x"), "at most 32"]] as const) {
      expect(() => validateSettings({ inspector: { [key]: value } })).toThrow(message);
    }
  });
});
