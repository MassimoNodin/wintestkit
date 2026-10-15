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
    for (const invalid of [
      null,
      "pick",
      {},
      { type: "execute" },
      { type: "select", nodeId: 1 },
      { type: "loadProperties", nodeId: 1 },
      { type: "select", nodeId: "x".repeat(513) },
      { type: "copy", text: "x".repeat(100001) },
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
