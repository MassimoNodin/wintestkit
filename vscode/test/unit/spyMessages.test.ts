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
    expect(
      parseSpyRequest({
        type: "loadProperties",
        nodeId: "node:1",
        full: false,
      }),
    ).toEqual({ type: "loadProperties", nodeId: "node:1" });
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
  it("accepts a pin request only for a property name and a boolean", () => {
    expect(parseSpyRequest({ type: "pinProperty", name: "HelpText", pinned: true, x: 1 })).toEqual({
      type: "pinProperty", name: "HelpText", pinned: true,
    });
    for (const request of [
      { name: "has space", pinned: true }, { name: "", pinned: true }, { name: "1Name", pinned: true },
      { name: "a".repeat(65), pinned: true }, { name: 5, pinned: true }, { name: "HelpText", pinned: "yes" },
      { name: "HelpText" },
    ])
      expect(parseSpyRequest({ type: "pinProperty", ...request })).toBeUndefined();
  });
});
