/** The default request timeout of the JSON-RPC client; a page check always gets at least this long. */
const BASE_MS = 30_000;
const PER_ELEMENT_MS = 4_000;
const MAX_MS = 10 * 60 * 1000;

/** How long a whole-page check may take: the base timeout plus a few seconds for every element, within a sensible cap. */
export function pageCheckTimeoutMs(elementCount: number): number {
  return Math.min(MAX_MS, BASE_MS + PER_ELEMENT_MS * Math.max(0, Math.floor(elementCount)));
}
