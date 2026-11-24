import { expect, it } from "vitest";
import { redact } from "../../src/diagnostics/redact";

it("redacts names as whole words only", () => {
  const counts: Record<string, number> = {};
  const out = redact("C:\\Users\\test\\x wintestkit test Massimo me@x.com HOST1 host1x", { user: "test", computer: ["HOST1"], domain: "", home: "C:\\Users\\test" }, counts);
  expect(out).toBe("<home>\\x wintestkit <user> Massimo <email> <computer> host1x");
});
