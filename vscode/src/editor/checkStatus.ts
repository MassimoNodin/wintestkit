import type { CheckResult } from "../protocol/generated";

/** Summary reflects the current screen; not-found results can be state-dependent. */
export function summarizeChecks(results: readonly CheckResult[]): string {
  const count = (status: CheckResult["status"]) =>
    results.filter((r) => r.status === status).length;
  const found = count("found");
  const broken = count("not_found");
  const errors = results.length - found - broken;
  return (
    "Checked " +
    results.length +
    " elements: " +
    found +
    " found, " +
    broken +
    " not found (possibly off-screen, broken, or moved)" +
    (errors ? ", " + errors + " errors" : "") +
    "."
  );
}
