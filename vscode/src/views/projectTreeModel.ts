import * as path from "node:path";
import type { DiscoveryResult } from "../protocol/generated";
import type { ElementNode } from "./elementsTreeModel";

/**
 * Flows listed like pages: one row per flow, with the file it lives in beside its name. Flows keep
 * their order within a file; files are ordered by name.
 */
export function buildProjectTree(
  discoveries: DiscoveryResult[],
): ElementNode[] {
  return discoveries.flatMap((discovery) => {
    const files = new Map<string, ElementNode[]>();
    for (const flow of discovery.flows ?? []) {
      const rows = files.get(flow.file) ?? [];
      rows.push({
        id: "flows|" + discovery.root + "|" + flow.id,
        label: flow.name,
        description: path.relative(discovery.root, flow.file),
        kind: "flow",
        icon: "run-all",
        children: [],
        file: flow.file,
        range: flow.nameRange,
        runnable: flow.runnable === true,
      });
      files.set(flow.file, rows);
    }
    const children = [...files.entries()]
      .sort(([first], [second]) =>
        path
          .relative(discovery.root, first)
          .localeCompare(path.relative(discovery.root, second)),
      )
      .flatMap(([, rows]) => rows);
    return discoveries.length > 1 && children.length
      ? [
          {
            id: "flows|" + discovery.root,
            label: path.basename(discovery.root),
            description: discovery.root,
            kind: "project" as const,
            icon: "root-folder",
            children,
          },
        ]
      : children;
  });
}
