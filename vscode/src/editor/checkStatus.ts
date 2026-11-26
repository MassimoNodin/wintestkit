import type { CheckResult } from "../protocol/generated";

/** Summary reflects the current screen; not-found results can be state-dependent. */
export function summarizeChecks(results: readonly CheckResult[]): string {
  const count = (status: CheckResult["status"]) =>
    results.filter((r) => r.status === status).length;
  const found = count("found");
  const broken = count("not_found");
  const busy = count("not_responding");
  const errors = results.length - found - broken - busy;
  return (
    "Checked " +
    results.length +
    " elements: " +
    found +
    " found, " +
    broken +
    " not found (possibly off-screen, broken, or moved)" +
    (busy ? ", " + busy + " not responding" : "") +
    (errors ? ", " + errors + " errors" : "") +
    "."
  );
}
