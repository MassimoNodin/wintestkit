import policy from "./compatibility.json";

export const EXTENSION_VERSION = policy.extensionVersion;
export const PROTOCOL_VERSION = policy.protocolVersion;
export const ALLOW_PRERELEASE = (policy as { channel?: string }).channel === "prerelease";
export const PYTHON_SPECIFIER = ">=" + policy.python.minimum + (ALLOW_PRERELEASE ? ".dev0" : "") + ",<" + policy.python.maximumExclusive;
export const PYTHON_REQUIREMENT = "wintestkit" + PYTHON_SPECIFIER;

export interface CompatibilityIssue {
  kind: "older" | "newer" | "unknown" | "protocol";
  message: string;
  updateExtension: boolean;
}

function release(version: unknown): number[] | undefined {
  if (typeof version !== "string") return;
  const match = /^(\d+)\.(\d+)(?:\.(\d+))?(?:(?:a|b|rc)\d+|\.dev\d+|\.post\d+)?(?:\+[a-zA-Z0-9]+(?:[._-][a-zA-Z0-9]+)*)?$/.exec(version);
  if (!match) return;
  const parts = [Number(match[1]), Number(match[2]), Number(match[3] ?? 0)];
  return parts.every(Number.isSafeInteger) ? parts : undefined;
}

export function compareReleaseVersions(first: unknown, second: unknown): number | undefined {
  const left = release(first);
  const right = release(second);
  if (!left || !right) return;
  for (let index = 0; index < left.length; index++) {
    const difference = left[index] - right[index];
    if (difference) return difference;
  }
  return 0;
}

export function packageCompatibility(version: unknown): CompatibilityIssue | undefined {
  const minimum = compareReleaseVersions(version, policy.python.minimum);
  const maximum = compareReleaseVersions(version, policy.python.maximumExclusive);
  const installed = typeof version === "string" && version ? version : "unknown";
  const context = "WinTestKit extension " + EXTENSION_VERSION + " requires " + PYTHON_REQUIREMENT +
    "; installed Python package: " + installed + ". ";
  if (minimum === undefined || maximum === undefined ||
      (!ALLOW_PRERELEASE && typeof version === "string" && /^\d+\.\d+(?:\.\d+)?(?:(?:a|b|rc)\d+|\.dev\d+)(?:\+|$)/.test(version)))
    return {
      kind: "unknown",
      message: context + "The package version is missing, invalid, or a prerelease not enabled by this extension's release channel. Install a compatible package or choose another interpreter.",
      updateExtension: false,
    };
  if (minimum < 0)
    return {
      kind: "older",
      message: context + "The Python package is too old. Install a compatible package or choose another interpreter.",
      updateExtension: false,
    };
  if (maximum >= 0)
    return {
      kind: "newer",
      message: context + "The Python package is too new. Update the WinTestKit extension, or install a compatible package to keep this extension.",
      updateExtension: true,
    };
}

export function protocolCompatibility(version: unknown, protocol: unknown): CompatibilityIssue | undefined {
  const issue = packageCompatibility(version);
  if (issue) return issue;
  if (protocol === PROTOCOL_VERSION) return;
  const known = typeof protocol === "number" && Number.isSafeInteger(protocol) && protocol > 0;
  const updateExtension = known && protocol > PROTOCOL_VERSION;
  return {
    kind: "protocol",
    message: "WinTestKit extension " + EXTENSION_VERSION + " requires protocol " + PROTOCOL_VERSION +
      " and " + PYTHON_REQUIREMENT + "; Python package " + String(version) + " reports protocol " +
      (known ? protocol : "unknown or invalid") + ". " +
      (updateExtension ? "Update the WinTestKit extension, or install a compatible package." : "Reinstall a compatible Python package or choose another interpreter."),
    updateExtension,
  };
}

export class CompatibilityError extends Error {
  constructor(readonly issue: CompatibilityIssue, readonly python: string) {
    super(issue.message + " Selected interpreter: " + python);
    this.name = "CompatibilityError";
  }
}
