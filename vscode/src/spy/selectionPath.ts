import type { NodeInfo } from "../protocol/generated";

/**
 * One level of the route from a root window down to a selected object.
 *
 * Node ids (runtime ids) do not survive a reload or a server restart, so a selection is
 * remembered by what the objects are: their properties, and their place among their siblings.
 */
export interface PathSegment {
  controlType: string;
  automationId: string;
  name: string;
  className: string;
  /** Position among the siblings when it was selected; absent for root windows. */
  index?: number;
}

export const MAX_PATH_DEPTH = 64;
const MAX_TEXT = 512;

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.length <= MAX_TEXT ? value : undefined;

/** Accepts only a well-formed path (from the webview or from saved state); anything else is dropped. */
export function parseSelectionPath(value: unknown): PathSegment[] | undefined {
  if (!Array.isArray(value) || value.length < 1 || value.length > MAX_PATH_DEPTH) return;
  const path: PathSegment[] = [];
  for (const entry of value as unknown[]) {
    if (!entry || typeof entry !== "object") return;
    const raw = entry as Record<string, unknown>;
    const controlType = text(raw.controlType);
    const automationId = text(raw.automationId);
    const name = text(raw.name);
    const className = text(raw.className);
    if (controlType === undefined || automationId === undefined || name === undefined || className === undefined)
      return;
    const segment: PathSegment = { controlType, automationId, name, className };
    if (raw.index !== undefined) {
      if (!Number.isInteger(raw.index) || (raw.index as number) < 0 || (raw.index as number) > 1_000_000) return;
      segment.index = raw.index as number;
    }
    path.push(segment);
  }
  return path;
}

export function segmentOf(info: NodeInfo["info"], index?: number): PathSegment {
  return {
    controlType: info.controlType,
    automationId: info.automationId,
    name: info.name,
    className: info.className,
    ...(index === undefined ? {} : { index }),
  };
}

/** How the user would recognise it: \`Pane "Editor"\`, \`Button #Save\` or just \`Pane\`. */
export function describeSegment(segment: PathSegment): string {
  const label = segment.name
    ? ' "' + (segment.name.length > 60 ? segment.name.slice(0, 57) + "..." : segment.name) + '"'
    : segment.automationId
      ? " #" + segment.automationId
      : segment.className
        ? " [" + segment.className + "]"
        : "";
  return segment.controlType + label;
}

const MIN_SHARED_NAME = 8;

/** Whether one name contains the other and the shared part is long enough to mean something. */
function related(left: string, right: string): boolean {
  const [short, long] = left.length <= right.length ? [left, right] : [right, left];
  return short.length >= MIN_SHARED_NAME && long.includes(short);
}

/** How well a candidate fits a segment, 0 for no match. Stronger identity scores higher. */
function score(segment: PathSegment, info: NodeInfo["info"]): number {
  if (info.controlType !== segment.controlType) return 0;
  const sameClass = info.className === segment.className;
  const sameId = !!segment.automationId && info.automationId === segment.automationId;
  const sameName = !!segment.name && info.name === segment.name;
  if (sameId && sameClass) return 90;
  if (sameId) return 80;
  if (sameName && sameClass) return 70;
  if (sameName) return 55;
  // A window title changes with the open file; keep matching when one holds the other. Short
  // names prove nothing ("y" is inside "Ready"), so only a substantial shared part counts.
  if (sameClass && related(segment.name, info.name)) return 50;
  if (sameClass && !segment.name && !segment.automationId && !info.name && !info.automationId) return 40;
  // Same kind of object but a different name or id: that is another object, not this one renamed.
  // Only its place among the siblings can vouch for it (see bestMatch).
  const contradicts = (!!segment.name && !!info.name) || (!!segment.automationId && !!info.automationId);
  if (sameClass && !contradicts) return 30;
  return 10;
}

/**
 * The candidate that is the object \`segment\` described, or undefined when there is no single
 * clear answer. A look-alike is never picked: if several fit equally well and the position among
 * the siblings does not settle it, the object counts as not found.
 */
export function bestMatch(segment: PathSegment, candidates: NodeInfo[]): NodeInfo | undefined {
  const scored = candidates.map((candidate, position) => {
    const base = score(segment, candidate.info);
    const here = segment.index !== undefined && segment.index === position;
    // Position settles ties, and rescues a weak match (type only) when the order is unchanged.
    return { candidate, value: base === 0 ? 0 : base + (here ? 5 : 0), weak: base === 10, here };
  });
  const best = Math.max(0, ...scored.map((entry) => entry.value));
  if (best === 0) return;
  const top = scored.filter((entry) => entry.value === best);
  if (top.length !== 1) return;
  const [only] = top;
  if (only.weak && !only.here) return;
  return only.candidate;
}
