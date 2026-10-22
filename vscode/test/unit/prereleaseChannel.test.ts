import { afterEach, describe, expect, it, vi } from "vitest";

async function channelPolicy(channel?: string) {
  vi.resetModules();
  vi.doMock("../../src/compatibility.json", () => ({ default: {
    extensionVersion: "0.1.1", python: { minimum: "0.1.1", maximumExclusive: "0.2.0" },
    protocolVersion: 1, ...(channel === undefined ? {} : { channel }),
  } }));
  vi.doMock("vscode", () => ({}));
  vi.doMock("@vscode/python-extension", () => ({ PythonExtension: {} }));
  return { ...await import("../../src/compatibility"), ...await import("../../src/python") };
}

afterEach(() => {
  vi.doUnmock("../../src/compatibility.json");
  vi.resetModules();
});

describe("explicit release channel", () => {
  it.each([undefined, "stable", "invalid"])("does not opt in with channel %s", async (channel) => {
    const policy = await channelPolicy(channel);
    expect(await policy.installArguments()).not.toContain("--pre");
    expect(policy.PYTHON_REQUIREMENT).toBe("wintestkit>=0.1.1,<0.2.0");
    expect(policy.packageCompatibility("0.1.1rc1")?.kind).toBe("unknown");
  });
  it.each(["0.1.1a1", "0.1.1b2", "0.1.1rc1", "0.1.1.dev0", "0.1.1.dev3", "0.1.99rc9", "0.1.1", "0.1.1rc1+local"])("accepts authorized package %s by release tuple", async (version) => {
    const policy = await channelPolicy("prerelease");
    expect(policy.EXTENSION_VERSION).toBe("0.1.1");
    expect(policy.packageCompatibility(version)).toBeUndefined();
    expect(policy.protocolCompatibility(version, 1)).toBeUndefined();
    expect(policy.protocolCompatibility(version, 2)?.kind).toBe("protocol");
    expect(await policy.installArguments()).toEqual([
      "-m", "pip", "install", "--upgrade", "--force-reinstall", "--pre", "wintestkit>=0.1.1.dev0,<0.2.0",
    ]);
    const { DevPackages } = await import("../../src/setup/devPackages");
    const packages = new DevPackages({ get: () => undefined } as never);
    expect(await packages.arguments({ toString: () => "file:///work" } as never)).toEqual(await policy.installArguments());
  });
  it.each([["0.1.0rc1", "older"], ["0.2.0.dev1", "newer"], ["0.2.0a1", "newer"], ["0.2.0rc1", "newer"], ["garbage", "unknown"], ["0.1.1preview1", "unknown"]])("rejects out-of-policy %s", async (version, kind) => {
    const policy = await channelPolicy("prerelease");
    expect(policy.packageCompatibility(version)?.kind).toBe(kind);
  });
});
