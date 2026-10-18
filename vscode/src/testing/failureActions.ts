import type { Diagnostic } from "../protocol/generated";

export interface TrustedMarkdown {
  appendMarkdown(value: string): void;
  isTrusted?: boolean | { readonly enabledCommands: readonly string[] };
}

export function appendRelocationAction(
  markdown: TrustedMarkdown,
  diagnostic: Diagnostic,
): void {
  const relocation = diagnostic.relocations?.[0];
  if (!relocation) return;
  const args = encodeURIComponent(JSON.stringify([relocation.path]));
  markdown.appendMarkdown(
    "\n\n[Reveal relocated element in Spy](command:wintestkit.spy.revealRelocation?" +
      args +
      ")",
  );
  markdown.isTrusted = {
    enabledCommands: ["wintestkit.spy.revealRelocation"],
  };
}
