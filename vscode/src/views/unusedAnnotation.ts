import type { ElementNode } from "./elementsTreeModel";

export interface UnusedLookup {
  /** The scan owner of a node (its project key), when the node belongs to a scanned project. */
  ownerOf(node: ElementNode): string | undefined;
  /** Whether a finished scan exists for this owner. */
  hasResult(owner: string): boolean;
  isUnused(owner: string, elementId: string): boolean;
}

export const UNUSED_NOTE = "possibly unused";
export const UNUSED_TOOLTIP =
  "Possibly unused: the Python language server found no references to this definition. This is a static estimate; dynamic access can hide real uses.";

/**
 * Marks scanned definitions that look unused. With ``onlyUnused`` it also prunes everything else
 * from projects that have a finished scan, keeping the ancestors needed to reach a match.
 */
export function annotateUnused(
  nodes: readonly ElementNode[],
  lookup: UnusedLookup,
  onlyUnused: boolean,
  inherited?: string,
): ElementNode[] {
  return nodes.flatMap((node) => {
    const owner = lookup.ownerOf(node) ?? inherited;
    const scanned = owner !== undefined && lookup.hasResult(owner);
    const unused =
      scanned && node.elementId !== undefined && lookup.isUnused(owner, node.elementId);
    const children = annotateUnused(node.children, lookup, onlyUnused, owner);
    if (onlyUnused && scanned && !unused && children.length === 0) return [];
    return [
      {
        ...node,
        description: unused
          ? [node.description, UNUSED_NOTE].filter(Boolean).join(" · ")
          : node.description,
        tooltip: unused
          ? [node.tooltip, UNUSED_TOOLTIP].filter(Boolean).join("\n\n")
          : node.tooltip,
        children,
      },
    ];
  });
}
