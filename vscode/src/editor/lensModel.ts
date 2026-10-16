import * as path from "node:path";
import type {
  DiscoveryResult,
  ElementHighlightResult,
  LocatorData,
  Matcher,
  TestOutcome,
  WindowLocatorData,
} from "../protocol/generated";

export interface LensSpec {
  line: number;
  title: string;
  command: string;
  args: unknown[];
  tooltip: string;
}
export type ElementAction = "highlight" | "check";
export type ActionStatus = ElementHighlightResult | { status: "running" };
export type ActionFeedback = Partial<Record<ElementAction, ActionStatus>>;

function actionLabel(action: ElementAction, result?: ActionStatus): string {
  if (!result) return "";
  if (result.status === "running")
    return (
      "$(loading~spin) " +
      (action === "highlight" ? "Highlighting…" : "Checking…")
    );
  if (result.status === "found")
    return (
      "$(pass-filled) " +
      (action === "highlight" ? "Highlighted" : "Check: Found")
    );
  if (result.status === "ambiguous")
    return (
      "$(warning) " +
      (action === "highlight" ? "Highlight: " : "Check: ") +
      (result.diagnostic?.matchCount ?? "Multiple") +
      " matches"
    );
  return (
    "$(error) " +
    (action === "highlight" ? "Highlight: " : "Check: ") +
    (result.status === "not_found" ? "Not found" : "Failed")
  );
}

function actionTooltip(
  result: ActionStatus | undefined,
  fallback: string,
): string {
  if (!result || result.status === "running") return fallback;
  return result.diagnostic?.message ?? result.message ?? fallback;
}
const matcher = (value: Matcher): string =>
  typeof value === "string"
    ? JSON.stringify(value)
    : "/" + value.regex + "/" + (value.flags ?? "");
const whereParts = (where: LocatorData["where"]): string[] =>
  Object.entries(where ?? {}).map(
    ([key, value]) =>
      key +
      "=" +
      (typeof value === "boolean" || typeof value === "number"
        ? JSON.stringify(value)
        : matcher(value)),
  );
export function describeWindow(window: WindowLocatorData): string {
  const parts: string[] = [];
  if (window.title !== undefined) parts.push("title=" + matcher(window.title));
  if (window.automationId !== undefined)
    parts.push("id=" + matcher(window.automationId));
  if (window.className !== undefined)
    parts.push("class=" + matcher(window.className));
  if (window.process !== undefined)
    parts.push("process=" + JSON.stringify(window.process));
  if (window.index !== undefined) parts.push("index=" + window.index);
  parts.push(...whereParts(window.where));
  return "Window" + (parts.length ? "[" + parts.join(", ") + "]" : "");
}
export function describeLocator(locator: LocatorData): string {
  const parts: string[] = [];
  if (locator.automationId !== undefined)
    parts.push("id=" + matcher(locator.automationId));
  if (locator.name !== undefined) parts.push("name=" + matcher(locator.name));
  if (locator.className !== undefined)
    parts.push("class=" + matcher(locator.className));
  if (locator.index !== undefined) parts.push("index=" + locator.index);
  if (locator.depth !== undefined) parts.push("depth=" + locator.depth);
  parts.push(...whereParts(locator.where));
  let result =
    (locator.controlType ?? "*") +
    (parts.length ? "[" + parts.join(", ") + "]" : "");
  if (locator.item) {
    const item = locator.item;
    result +=
      item.kind === "row"
        ? " > row(" + item.row + ")"
        : " > cell(" + item.row + ", " + JSON.stringify(item.column) + ")";
  }
  if (locator.within) result = describeLocator(locator.within) + " > " + result;
  if (locator.window) result = describeWindow(locator.window) + " >> " + result;
  return result;
}
export function buildLenses(
  discovery: DiscoveryResult,
  file: string,
  lastResults: Map<string, TestOutcome>,
  feedback: ReadonlyMap<string, ActionFeedback> = new Map(),
): LensSpec[] {
  const normalize = (value: string): string => {
    const resolved =
      process.platform === "win32"
        ? path.win32.resolve(value).toLowerCase()
        : path.resolve(value);
    return resolved.replaceAll("\\", "/");
  };
  const lenses: LensSpec[] = [];
  const add = (
    line: number,
    title: string,
    command: string,
    args: unknown,
    tooltip: string,
  ) =>
    lenses.push({
      line,
      title: title.replace(/(\$\([^)]+\)) /g, "$1\u00a0\u00a0"),
      command,
      args: command ? [args] : [],
      tooltip,
    });
  for (const page of discovery.pages) {
    if (normalize(page.file) !== normalize(file)) continue;
    add(
      page.range.start.line,
      "$(checklist) Check all elements",
      "wintestkit.checkPage",
      { file, page: page.qualname },
      page.qualname,
    );
    for (const element of page.elements) {
      const status = feedback.get(element.id);
      const tooltip =
        element.kind === "window"
          ? describeWindow(element.locator.window ?? {})
          : describeLocator(element.locator);
      add(
        element.range.start.line,
        actionLabel("highlight", status?.highlight) ||
          "$(eye) Highlight " +
            (element.kind === "window" ? "window" : "element"),
        "wintestkit.highlightElement",
        { file, qualname: element.qualname },
        actionTooltip(status?.highlight, tooltip),
      );
      if (element.kind !== "window")
        add(
          element.range.start.line,
          actionLabel("check", status?.check) || "$(check) Check",
          "wintestkit.checkElement",
          { file, qualname: element.qualname },
          actionTooltip(status?.check, tooltip),
        );
    }
  }
  for (const test of discovery.tests) {
    if (normalize(test.file) !== normalize(file)) continue;
    const suffix = test.kind === "class" ? "tests" : "test";
    add(
      test.range.start.line,
      "$(play) Run " + suffix,
      "wintestkit.runTest",
      { id: test.id },
      test.id,
    );
    add(
      test.range.start.line,
      "$(debug-alt) Debug " + suffix,
      "wintestkit.debugTest",
      { id: test.id },
      test.id,
    );
    const outcome = lastResults.get(test.id);
    if (outcome) {
      const title =
        outcome === "passed"
          ? "$(pass-filled) Passed"
          : outcome === "skipped"
            ? "$(debug-step-over) Skipped"
            : "$(error) Failed";
      add(test.range.start.line, title, "", undefined, outcome);
    }
  }
  return lenses;
}
