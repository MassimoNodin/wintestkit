import { describe, expect, it } from "vitest";
import { settingFields, updateSetting, validateSettings } from "../../src/settings/model";

describe("inspector settings", () => {
  it("exposes all five keys in both scopes", () => {
    for (const key of ["enabled", "attach", "attach_timeout", "request_timeout", "redact_names"]) {
      const field = settingFields.find((item) => item.key === `inspector.${key}`);
      expect(field).toBeDefined(); expect(field?.localOnly).not.toBe(true); expect(field?.repositoryOnly).not.toBe(true);
    }
    for (const scope of ["shared", "local"] as const) expect(updateSetting("", scope, "inspector.enabled", true, false)).toContain("enabled: true");
  });
  it("validates types, bounds and messages", () => {
    validateSettings({ inspector: { enabled: true, attach: "on-demand", attach_timeout: 10, request_timeout: 2, redact_names: ["x".repeat(128)] } });
    for (const [key, value, message] of [["enabled", 1, "true or false"], ["attach", "auto", "Invalid"], ["attach_timeout", 0, "positive number"], ["attach_timeout", 10.1, "positive number"], ["request_timeout", 0, "positive number"], ["request_timeout", 2.1, "positive number"], ["redact_names", [""], "at most 32"], ["redact_names", ["x".repeat(129)], "128 characters"], ["redact_names", Array(33).fill("x"), "at most 32"]] as const) {
      expect(() => validateSettings({ inspector: { [key]: value } })).toThrow(message);
    }
  });
});
