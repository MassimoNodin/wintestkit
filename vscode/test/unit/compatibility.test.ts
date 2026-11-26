import { describe, expect, it } from "vitest";
import { ALLOW_PRERELEASE, compareReleaseVersions, UPGRADE_LABEL, UPGRADE_REQUIREMENT, packageCompatibility, protocolCompatibility, PYTHON_REQUIREMENT } from "../../src/compatibility";

describe("compatibility policy", () => {
  it.each(["0.1.1", "0.1.2", "0.1.99", "0.1.1.post1", "0.1.1+local", "0.1.1+rc1", "0.1.1+beta1"])("accepts supported stable package %s", (version) => {
    expect(packageCompatibility(version)).toBeUndefined();
    expect(protocolCompatibility(version, 1)).toBeUndefined();
  });
  it.each([undefined, null, "", "garbage", 1, "0.1.9007199254740992"])("rejects unknown or unstable package %s", (version) => {
    expect(packageCompatibility(version)?.kind).toBe("unknown");
  });
  const prereleases = ["0.1.2a1", "0.1.2b1", "0.1.2rc1", "0.1.2.dev1"];
  it.each(prereleases)("%s follows the release channel", (version) => {
    expect(packageCompatibility(version)?.kind).toBe(ALLOW_PRERELEASE ? undefined : "unknown");
  });
  it("bounds both sides and recommends the correct fix", () => {
    expect(PYTHON_REQUIREMENT).toBe("wintestkit>=0.1.1rc7,<0.2.0");
    expect(packageCompatibility("0.1.0")).toMatchObject({ kind: "older", updateExtension: false });
    expect(packageCompatibility("0.2.0rc1")).toMatchObject({ kind: "newer", updateExtension: true });
    expect(packageCompatibility("0.2.0")).toMatchObject({ kind: "newer", updateExtension: true });
    expect(packageCompatibility("1.0.0")?.message).toContain("Update");
  });
  it("orders prereleases, final releases, post releases and ignores local labels", () => {
    const versions = ["0.1.1.dev0", "0.1.1a1", "0.1.1b1", "0.1.1rc1", "0.1.1rc3", "0.1.1", "0.1.1.post1"];
    for (let index = 1; index < versions.length; index++)
      expect(compareReleaseVersions(versions[index - 1], versions[index])).toBeLessThan(0);
    expect(compareReleaseVersions("0.1.1rc3+local", "0.1.1rc3+other")).toBe(0);
    expect(packageCompatibility("0.1.1rc1")?.kind).toBe("older");
    expect(packageCompatibility("0.1.1rc3", "0.1.1rc1")?.kind).toBe("older");
    expect(packageCompatibility("0.1.1", "0.1.1rc3")?.kind).toBe("older");
    expect(packageCompatibility("0.1.1rc7", "0.1.1rc7+local")).toBeUndefined();
    expect(UPGRADE_LABEL).toBe("Upgrade wintestkit to 0.1.1rc7");
    expect(UPGRADE_REQUIREMENT).toBe("wintestkit[inspector]==0.1.1rc7");
  });
  it.each([undefined, null, "1", 0, -1, 1.5, 2])("rejects incompatible protocol %s", (protocol) => {
    const issue = protocolCompatibility("0.1.1", protocol);
    expect(issue?.kind).toBe("protocol");
    expect(issue?.updateExtension).toBe(protocol === 2);
  });
});
