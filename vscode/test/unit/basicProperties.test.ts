import { describe, expect, it } from "vitest";
import {
  BASIC_GROUPS,
  DEFAULT_BASIC_PROPERTIES,
  MAX_BASIC_PROPERTIES,
  basicUiaNames,
  isBasicKey,
  normalizeBasicProperties,
} from "../../src/spy/basicProperties";

describe("Basic view keys", () => {
  it("accepts a known group, a slash and a row name, and nothing else", () => {
    for (const group of BASIC_GROUPS) expect(isBasicKey(`${group}/Some row`)).toBe(true);
    for (const bad of ["Enabled", "Standard", "Standard/", "standard/Enabled", "Bindings/Name", "Standard/a\nb", `Standard/${"a".repeat(201)}`, 5, undefined, null, {}])
      expect(isBasicKey(bad), String(bad)).toBe(false);
    expect(isBasicKey(`Standard/${"a".repeat(200)}`)).toBe(true);
    // A dot in ".NET" is a dot, not any character.
    expect(isBasicKey("XNET/Name")).toBe(false);
  });

  it("has a default that is the built-in Basic rows, every one a valid key without repeats", () => {
    expect(DEFAULT_BASIC_PROPERTIES.every(isBasicKey)).toBe(true);
    expect(new Set(DEFAULT_BASIC_PROPERTIES).size).toBe(DEFAULT_BASIC_PROPERTIES.length);
    expect(DEFAULT_BASIC_PROPERTIES.filter((key) => key.startsWith("Standard/"))).toEqual(
      ["Enabled", "Height", "Name", "Parent", "Visible", "Width"].map((name) => `Standard/${name}`),
    );
    expect(DEFAULT_BASIC_PROPERTIES.filter((key) => key.startsWith("Win32 Window/"))).toEqual(
      ["Window Class", "Control ID", "Text", "Handle", "Styles"].map((name) => `Win32 Window/${name}`),
    );
    expect(DEFAULT_BASIC_PROPERTIES).toContain(".NET/WPFControlText");
    expect(DEFAULT_BASIC_PROPERTIES).toContain(".NET/WinFormsControlText");
  });

  it("normalizes a stored list: keys only, no repeats, in order, at most the limit; anything else is empty", () => {
    expect(normalizeBasicProperties(["Standard/Name", "x", "Standard/Name", 5, ".NET/Content"])).toEqual(["Standard/Name", ".NET/Content"]);
    for (const value of ["Standard/Name", undefined, null, 5, { 0: "Standard/Name" }]) expect(normalizeBasicProperties(value)).toEqual([]);
    expect(normalizeBasicProperties(Array.from({ length: MAX_BASIC_PROPERTIES + 10 }, (_, index) => `Standard/P${index}`))).toHaveLength(MAX_BASIC_PROPERTIES);
  });

  it("names the UI Automation properties the server must read, skipping names it cannot", () => {
    expect(basicUiaNames(["Standard/Name", "UI Automation/HelpText", "UI Automation/not a name", "UI Automation/Orientation", ".NET/HelpText"])).toEqual(["HelpText", "Orientation"]);
    expect(basicUiaNames(DEFAULT_BASIC_PROPERTIES)).toEqual([]);
  });
});
