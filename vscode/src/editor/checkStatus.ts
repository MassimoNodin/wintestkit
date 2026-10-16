import type { CheckResult } from "../protocol/generated";

/** Status-bar summary of a page check; not found = broken or moved. */
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
    " broken/moved" +
    (errors ? ", " + errors + " errors" : "") +
    "."
  );
}
