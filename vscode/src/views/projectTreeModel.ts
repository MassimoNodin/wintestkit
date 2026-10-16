import * as path from "node:path";
import type { DiscoveryResult } from "../protocol/generated";
import type { ElementNode } from "./elementsTreeModel";

export function buildProjectTree(discoveries: DiscoveryResult[]): ElementNode[] {
  return discoveries.flatMap((discovery) => {
    const files = new Map<string, ElementNode>();
    for (const flow of discovery.flows ?? []) {
      const relative = path
        .relative(discovery.root, flow.file)
        .replaceAll("\\", "/");
      let file = files.get(flow.file);
      if (!file) {
        file = {
          id: "flows|" + discovery.root + "|" + relative,
          label: relative.startsWith("flows/")
            ? relative.slice("flows/".length)
            : relative,
          description: "",
          kind: "file",
          icon: "file-code",
          children: [],
          file: flow.file,
        };
        files.set(flow.file, file);
      }
      file.children.push({
        id: "flows|" + discovery.root + "|" + flow.id,
        label: flow.name,
        description: "",
        kind: "flow",
        icon: "symbol-method",
        children: [],
        file: flow.file,
        range: flow.nameRange,
        runnable: flow.runnable === true,
      });
    }
    const children = [...files.values()].sort((first, second) =>
      first.label.localeCompare(second.label),
    );
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
