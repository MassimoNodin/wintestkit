import { describe, expect, it } from "vitest";
import { packageCompatibility, protocolCompatibility, PYTHON_REQUIREMENT } from "../../src/compatibility";

describe("compatibility policy", () => {
  it.each(["0.1.1", "0.1.2", "0.1.99", "0.1.1.post1", "0.1.1+local"])("accepts supported stable package %s", (version) => {
    expect(packageCompatibility(version)).toBeUndefined();
    expect(protocolCompatibility(version, 1)).toBeUndefined();
  });
  it.each([undefined, null, "", "garbage", "0.1.2rc1", "0.1.2.dev1", 1, "0.1.9007199254740992"])("rejects unknown or unstable package %s", (version) => {
    expect(packageCompatibility(version)?.kind).toBe("unknown");
  });
  it("bounds both sides and recommends the correct fix", () => {
    expect(PYTHON_REQUIREMENT).toBe("wintestkit>=0.1.1,<0.2.0");
    expect(packageCompatibility("0.1.0")).toMatchObject({ kind: "older", updateExtension: false });
    expect(packageCompatibility("0.2.0")).toMatchObject({ kind: "newer", updateExtension: true });
    expect(packageCompatibility("1.0.0")?.message).toContain("Update");
  });
  it.each([undefined, null, "1", 0, -1, 1.5, 2])("rejects incompatible protocol %s", (protocol) => {
    const issue = protocolCompatibility("0.1.1", protocol);
    expect(issue?.kind).toBe("protocol");
    expect(issue?.updateExtension).toBe(protocol === 2);
  });
});
