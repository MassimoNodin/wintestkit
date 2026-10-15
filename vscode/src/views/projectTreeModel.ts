import * as path from "node:path";
import type { DiscoveryResult } from "../protocol/generated";
import type { ElementNode } from "./elementsTreeModel";

export type ProjectSection = "flows" | "tests";

export function buildProjectTree(
  discoveries: DiscoveryResult[],
  section: ProjectSection,
): ElementNode[] {
  return discoveries.flatMap((discovery) => {
    const files = new Map<string, ElementNode>();
    const entries = new Map<string, ElementNode>();
    const definitions =
      section === "tests"
        ? discovery.tests
        : (discovery.flows ?? []).map((flow) => ({
            ...flow,
            parent: null,
            kind: "function" as const,
          }));
    for (const definition of definitions) {
      const relative = path
        .relative(discovery.root, definition.file)
        .replaceAll("\\", "/");
      if (!files.has(definition.file)) {
        files.set(definition.file, {
          id: section + "|" + discovery.root + "|" + relative,
          label: relative.startsWith(section + "/")
            ? relative.slice(section.length + 1)
            : relative,
          description: "",
          kind: "file",
          icon: "file-code",
          children: [],
          file: definition.file,
          root: discovery.root,
          testId: section === "tests" ? relative : undefined,
        });
      }
      const isClass = definition.kind === "class";
      entries.set(definition.id, {
        id: section + "|" + discovery.root + "|" + definition.id,
        label: definition.name,
        description: "",
        kind: section === "flows" ? "flow" : isClass ? "test-class" : "test",
        icon:
          section === "flows"
            ? "symbol-method"
            : isClass
              ? "symbol-class"
              : "beaker",
        children: [],
        file: definition.file,
        range: definition.nameRange,
        root: discovery.root,
        testId: section === "tests" ? definition.id : undefined,
      });
    }
    for (const definition of definitions) {
      const parentId = definition.parent;
      const parent =
        (parentId && entries.get(parentId)) || files.get(definition.file);
      parent?.children.push(entries.get(definition.id)!);
    }
    const children = [...files.values()].sort((first, second) =>
      first.label.localeCompare(second.label),
    );
    return discoveries.length > 1 && children.length
      ? [
          {
            id: section + "|" + discovery.root,
            label: path.basename(discovery.root),
            description: discovery.root,
            kind: "project" as const,
            icon: "root-folder",
            children,
            root: discovery.root,
            testId: section === "tests" ? "" : undefined,
          },
        ]
      : children;
  });
}
