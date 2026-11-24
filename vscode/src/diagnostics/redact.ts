import * as os from "node:os";

export type Counts = Record<string, number>;
export interface Identities { user: string; computer: string[]; domain: string; home: string }
export function identities(): Identities {
  let user = "";
  try { user = os.userInfo().username; } catch { /* unavailable */ }
  return { user, computer: [os.hostname(), process.env.COMPUTERNAME ?? ""], domain: process.env.USERDOMAIN ?? "", home: os.homedir() };
}
export function redact(text: string, ids: Identities, counts: Counts): string {
  const rules: [string, string[]][] = [
    ["home", [ids.home, ids.home.replace(/\\/g, "/"), ids.home.replace(/\\/g, "\\\\")]],
    ["email", []], ["user", [ids.user]], ["computer", ids.computer], ["domain", [ids.domain]],
  ];
  for (const [label, values] of rules) {
    const unique = [...new Set(values.filter(Boolean))].sort((a, b) => b.length - a.length);
    const alternatives = unique.map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    // Names match whole words only: a user named "test" must not rewrite "wintestkit test".
    const whole = label === "user" || label === "computer" || label === "domain";
    const pattern = label === "email" ? /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi : unique.length ? new RegExp(whole ? `(?<![A-Za-z0-9_])(?:${alternatives})(?![A-Za-z0-9_])` : alternatives, "gi") : undefined;
    if (pattern) text = text.replace(pattern, () => { counts[label] = (counts[label] ?? 0) + 1; return `<${label}>`; });
  }
  return text;
}
export function redactSecrets(value: unknown, counts?: Counts): unknown {
  if (Array.isArray(value)) return value.map((item) => redactSecrets(item, counts));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    if (/password|token|secret|key|credential/i.test(key)) { if (counts) counts.secretKeys = (counts.secretKeys ?? 0) + 1; return [key, "<redacted>"]; }
    return [key, redactSecrets(item, counts)];
  }));
  return value;
}
export const LIMIT = 5 * 1024 * 1024;
export function truncate(text: string): string {
  const data = Buffer.from(text);
  if (data.length <= LIMIT) return text;
  const prefix = Buffer.from("[Truncated: earlier content omitted]\n");
  let start = data.length - (LIMIT - prefix.length);
  while (start < data.length && (data[start] & 0xc0) === 0x80) start++;
  return prefix.toString() + data.subarray(start).toString("utf8");
}
