import { describe, expect, it } from "vitest";
import { parseSpyRequest, suggestionText } from "../../src/spy/messages";

describe("Spy message contract", () => {
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
    expect(parseSpyRequest({
      type: "insertAssertion", nodeId: "node:1", definitionId: "pages/a.py::A.ok",
      name: "OK", enabled: true,
    })).toEqual({
      type: "insertAssertion", nodeId: "node:1", definitionId: "pages/a.py::A.ok",
      name: "OK", enabled: true,
    });
    expect(
      parseSpyRequest({ type: "openDefinition", id: "pages/a.py::A.b", x: 1 }),
    ).toEqual({ type: "openDefinition", id: "pages/a.py::A.b" });
    expect(parseSpyRequest({ type: "ready", showOtherApps: true })).toEqual({
      type: "ready",
      showOtherApps: true,
    });
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
  it("formats helpers before the picked element", () => {
    expect(
      suggestionText({
        locator: {},
        code: 'Element(name="OK", within=panel)',
        attributeName: "ok",
        helpers: [
          {
            attributeName: "panel",
            code: 'Element(name="Panel")',
            locator: {},
          },
        ],
        unique: true,
        matchCount: 1,
        strategy: "within",
      }),
    ).toBe(
      'panel = Element(name="Panel")\nok = Element(name="OK", within=panel)',
    );
  });
});
