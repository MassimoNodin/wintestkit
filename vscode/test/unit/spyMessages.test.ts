import { describe, expect, it } from "vitest";
import { parseSpyRequest, SPY_TOUR_ACTIONS } from "../../src/spy/messages";

describe("Spy message contract", () => {
  it("accepts only navigation actions from the optional tutorial", () => {
    for (const action of SPY_TOUR_ACTIONS)
      expect(parseSpyRequest({ type: "tour", action })).toEqual({ type: "tour", action });
    for (const action of [undefined, "launch", "pickApp", "execute", 12])
      expect(parseSpyRequest({ type: "tour", action })).toBeUndefined();
  });
  it("allows only known message types and validates payloads", () => {
    expect(
      parseSpyRequest({ type: "select", nodeId: "node:1", extra: "ignored" }),
    ).toEqual({ type: "select", nodeId: "node:1" });
    // Every property loads with the selection; there is no request for a button to send.
    expect(
      parseSpyRequest({ type: "loadProperties", nodeId: "node:1" }),
    ).toBeUndefined();
    expect(
      parseSpyRequest({ type: "copy", text: "button = Element()" }),
    ).toBeDefined();
    expect(
      parseSpyRequest({ type: "openDefinition", id: "pages/a.py::A.b", x: 1 }),
    ).toEqual({ type: "openDefinition", id: "pages/a.py::A.b" });
    expect(parseSpyRequest({ type: "ready", showOtherApps: true })).toEqual({
      type: "ready",
      showOtherApps: true,
    });
    expect(parseSpyRequest({ type: "chooseApp" })).toEqual({ type: "chooseApp" });
    expect(parseSpyRequest({ type: "openGettingStarted" })).toBeUndefined();
    expect(parseSpyRequest({ type: "ready", showOtherApps: "yes" })).toEqual({
      type: "ready",
    });
    expect(parseSpyRequest({ type: "bringToFront", enabled: true })).toEqual({
      type: "bringToFront",
      enabled: true,
    });
    expect(parseSpyRequest({ type: "showOtherApps", enabled: false })).toEqual({
      type: "showOtherApps",
      enabled: false,
    });
    for (const invalid of [
      null,
      "pick",
      {},
      { type: "execute" },
      { type: "launchApp" },
      { type: "showOtherApps" },
      { type: "showOtherApps", enabled: "yes" },
      { type: "bringToFront" },
      { type: "bringToFront", enabled: "yes" },
      { type: "select", nodeId: 1 },
      { type: "loadProperties", nodeId: 1 },
      { type: "select", nodeId: "x".repeat(513) },
      { type: "copy", text: "x".repeat(100001) },
      { type: "openDefinition" },
      { type: "openDefinition", id: 3 },
      { type: "openDefinition", id: "x".repeat(2049) },
    ])
      expect(parseSpyRequest(invalid)).toBeUndefined();
  });
  it("does not accept caller-controlled suggestion code for insertion", () => {
    expect(
      parseSpyRequest({ type: "addToPage", suggestion: { code: "unsafe" } }),
    ).toEqual({ type: "addToPage" });
  });
  it("accepts a Basic view request only for a group-qualified key and a boolean", () => {
    expect(parseSpyRequest({ type: "basicProperty", key: "Standard/Enabled", pinned: true, x: 1 })).toEqual({
      type: "basicProperty", key: "Standard/Enabled", pinned: true,
    });
    for (const key of ["Standard/Enabled", "Extended/AutomationId", ".NET/Content", "Win32 Window/Window Class", "UI Automation/HelpText"])
      expect(parseSpyRequest({ type: "basicProperty", key, pinned: false })).toEqual({ type: "basicProperty", key, pinned: false });
    for (const request of [
      { key: "Enabled", pinned: true }, { key: "Other/Enabled", pinned: true }, { key: "Standard/", pinned: true },
      { key: "Standard/" + "a".repeat(201), pinned: true }, { key: "Standard/a\nb", pinned: true }, { key: 5, pinned: true },
      { key: "Standard/Enabled", pinned: "yes" }, { key: "Standard/Enabled" }, { key: "standard/Enabled", pinned: true },
    ])
      expect(parseSpyRequest({ type: "basicProperty", ...request })).toBeUndefined();
    expect(parseSpyRequest({ type: "pinProperty", name: "HelpText", pinned: true })).toBeUndefined();
  });
  it("accepts the reset request", () => {
    expect(parseSpyRequest({ type: "resetBasicProperties", extra: 1 })).toEqual({ type: "resetBasicProperties" });
  });
  it("accepts a tree width in pixels, or null to forget it, and nothing else", () => {
    expect(parseSpyRequest({ type: "treeWidth", width: 412.4 })).toEqual({ type: "treeWidth", width: 412 });
    expect(parseSpyRequest({ type: "treeWidth", width: null })).toEqual({ type: "treeWidth", width: null });
    for (const width of [99, 10001, NaN, Infinity, "400", undefined, -5])
      expect(parseSpyRequest({ type: "treeWidth", width })).toBeUndefined();
  });
});
