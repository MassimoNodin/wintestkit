export type AssertionKind = "text" | "enabled";

export function assertionLine(
  kind: AssertionKind,
  expression: string,
  observed: string | boolean,
): string {
  return kind === "text"
    ? `expect(${expression}).to_have_text(${JSON.stringify(observed)})`
    : `expect(${expression}).to_be_${observed ? "enabled" : "disabled"}()`;
}
