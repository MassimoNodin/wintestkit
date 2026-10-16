import type { Diagnostic, ElementInfo } from "../protocol/generated";

export function shortElement(info: ElementInfo): string {
  const parts = [info.controlType];
  if (info.automationId) parts.push("#" + info.automationId);
  if (info.name) parts.push('"' + info.name + '"');
  if (!info.automationId && !info.name && info.className)
    parts.push("[" + info.className + "]");
  return parts.join(" ");
}
export function formatDiagnostic(diagnostic: Diagnostic): string {
  const lines = [
    diagnostic.message,
    "  Locator: " + diagnostic.locator,
    "  Searched in: " + diagnostic.searchedIn,
  ];
  if (diagnostic.candidates.length) lines.push("  Candidates:");
  diagnostic.candidates.slice(0, 5).forEach((candidate, index) => {
    const info = candidate.info;
    let text = "  " + (index + 1) + ". " + shortElement(info);
    if (info.className) text += " [class=" + info.className + "]";
    if (info.rect)
      text +=
        " at (" +
        info.rect.left +
        "," +
        info.rect.top +
        " " +
        info.rect.width +
        "x" +
        info.rect.height +
        ")";
    if (candidate.mismatches.length)
      text +=
        " \u2014 " +
        candidate.mismatches
          .map(
            (mismatch) =>
              mismatch.property +
              ": expected " +
              mismatch.expected +
              ", got " +
              mismatch.actual,
          )
          .join("; ");
    lines.push(text);
  });
  const roots = new Map<string, string[]>();
  for (const found of diagnostic.relocations ?? []) {
    if (found.kind === "element" && found.sameWindow) {
      lines.push(
        "  → found in the same window under a different container: " +
          found.path,
      );
    } else if (found.kind === "element") {
      lines.push("  → found in another window: " + found.path);
    } else {
      roots.set(found.target, [
        ...(roots.get(found.target) ?? []),
        found.window,
      ]);
    }
  }
  roots.forEach((windows, target) =>
    lines.push(
      "  → the component root " +
        target +
        " was found in: " +
        [...new Set(windows)].join(", "),
    ),
  );
  if (diagnostic.relocations?.length) {
    if (diagnostic.hint) lines.push("  hint: " + diagnostic.hint);
    if (diagnostic.declared) lines.push("  declared: " + diagnostic.declared);
  }
  return lines.join("\n");
}
