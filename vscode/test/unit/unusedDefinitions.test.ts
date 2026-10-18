import { describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
vi.mock("vscode", () => ({}));
import { isUnusedFromReferences } from "../../src/views/unusedDefinitions";

describe("unused definition reference classification", () => {
  const uri = { toString: () => "file:///project/page.py" } as vscode.Uri;
  const position = { line: 2, character: 4 } as vscode.Position;
  const declaration = { uri, range: { contains: (value: vscode.Position) => value === position } } as vscode.Location;
  it("marks a declaration with no other references as unused", () => {
    expect(isUnusedFromReferences([declaration], uri, position)).toBe(true);
  });
  it("does not mark definitions with references elsewhere as unused", () => {
    const usage = { uri: { toString: () => "file:///project/test.py" }, range: { contains: () => false } } as unknown as vscode.Location;
    expect(isUnusedFromReferences([declaration, usage], uri, position)).toBe(false);
  });
  it("treats an empty provider answer as unknown, not unused", () => {
    expect(isUnusedFromReferences([], uri, position)).toBeUndefined();
  });
  it("leaves unavailable provider results unknown", () => {
    expect(isUnusedFromReferences(undefined, uri, position)).toBeUndefined();
  });
});
