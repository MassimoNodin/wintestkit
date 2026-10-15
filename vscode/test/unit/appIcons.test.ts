import { describe, expect, it } from "vitest";
import {
  parseApplicationIcons,
  readApplicationIcons,
} from "../../src/spy/appIcons";

describe("Application icons", () => {
  it("accepts PNG data URIs keyed by numeric process IDs, including PowerShell BOM", () => {
    expect(
      parseApplicationIcons('\uFEFF{"123":"data:image/png;base64,aGVsbG8="}'),
    ).toEqual({ "123": "data:image/png;base64,aGVsbG8=" });
  });
  it("rejects external URLs, SVGs, invalid IDs and oversized values", () => {
    expect(
      parseApplicationIcons(
        JSON.stringify({
          "12": "https://example.com/icon.png",
          "13": "data:image/svg+xml;base64,abcd",
          "14": "data:image/png;base64," + "a".repeat(262144),
          "not-a-pid": "data:image/png;base64,abcd",
          "15": 42,
        }),
      ),
    ).toEqual({});
  });
  it("rejects non-object payloads", () => {
    expect(parseApplicationIcons("null")).toEqual({});
    expect(parseApplicationIcons("[]")).toEqual({});
  });
  it("does not launch extraction for empty or invalid process IDs", async () => {
    expect(await readApplicationIcons([0, -1, NaN, Infinity, 1.5])).toEqual({});
  });
});
