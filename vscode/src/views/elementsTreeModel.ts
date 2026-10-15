import * as path from "node:path";
import type { DiscoveryResult, Range } from "../protocol/generated";
import { describeLocator, describeWindow } from "../editor/lensModel";

export interface ElementNode {
  id: string;
  label: string;
  description: string;
  kind:
    | "project"
    | "page"
    | "window"
    | "element"
    | "elements"
    | "file"
    | "flow"
    | "test"
    | "test-class";
  icon: string;
  children: ElementNode[];
  file?: string;
  range?: Range;
  qualname?: string;
  page?: string;
  elementId?: string;
  tooltip?: string;
  root?: string;
  testId?: string;
}

export function buildTree(discoveries: DiscoveryResult[]): ElementNode[] {
  return discoveries.flatMap<ElementNode>((discovery) => {
    const pages = [...discovery.pages]
      .sort((first, second) => first.name.localeCompare(second.name))
      .map((page) => {
        const ordered = [...page.elements].sort(
          (first, second) =>
            Number(second.kind === "window") -
              Number(first.kind === "window") ||
            first.range.start.line - second.range.start.line,
        );
        const elements = new Map(
          ordered.map((element) => {
            const description =
              element.kind === "window"
                ? describeWindow(element.locator.window ?? {})
                : describeLocator({
                    ...element.locator,
                    within: undefined,
                    window: undefined,
                  });
            const node: ElementNode = {
              id: discovery.root + "|" + element.id,
              elementId: element.id,
              label: element.name,
              description,
              kind: element.kind,
              icon:
                element.kind === "window"
                  ? "window"
                  : element.kind === "elements"
                    ? "list-flat"
                    : "symbol-field",
              children: [],
              file: page.file,
              qualname: element.qualname,
              page: page.qualname,
              range: element.nameRange,
              tooltip:
                (element.kind === "window"
                  ? description
                  : describeLocator(element.locator)) +
                "\n" +
                page.file +
                ":" +
                (element.nameRange.start.line + 1),
            };
            return [element.name, node] as const;
          }),
        );
        const children: ElementNode[] = [];
        for (const element of ordered) {
          const node = elements.get(element.name)!;
          let ancestor = element;
          const seen = new Set([element.name]);
          let cyclic = false;
          while (ancestor.withinName) {
            if (seen.has(ancestor.withinName)) {
              cyclic = true;
              break;
            }
            seen.add(ancestor.withinName);
            const parent = ordered.find(
              (candidate) => candidate.name === ancestor.withinName,
            );
            if (!parent) break;
            ancestor = parent;
          }
          const parent =
            element.kind !== "window" && !cyclic && element.withinName
              ? elements.get(element.withinName)
              : undefined;
          if (parent) parent.children.push(node);
          else children.push(node);
        }
        return {
          id: discovery.root + "|" + page.id,
          label: page.name,
          description: path.relative(discovery.root, page.file),
          kind: "page" as const,
          icon: "symbol-class",
          children,
          file: page.file,
          range: page.nameRange,
          page: page.qualname,
        };
      });
    return discoveries.length > 1
      ? [
          {
            id: discovery.root,
            label: path.basename(discovery.root),
            description: discovery.root,
            kind: "project" as const,
            icon: "root-folder",
            children: pages,
          },
        ]
      : pages;
  });
}
