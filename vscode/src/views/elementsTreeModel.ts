import * as path from "node:path";
import type { DiscoveryResult, Range } from "../protocol/generated";
import { describeLocator, describeWindow } from "../editor/lensModel";

export interface ElementNode {
  id: string;
  label: string;
  description: string;
  kind: "project" | "screen" | "window" | "element" | "elements";
  icon: string;
  children: ElementNode[];
  file?: string;
  range?: Range;
  qualname?: string;
  screen?: string;
  elementId?: string;
  tooltip?: string;
}

export function buildTree(discoveries: DiscoveryResult[]): ElementNode[] {
  return discoveries.flatMap<ElementNode>((discovery) => {
    const screens = [...discovery.screens]
      .sort((first, second) => first.name.localeCompare(second.name))
      .map((screen) => {
        const ordered = [...screen.elements].sort(
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
              file: screen.file,
              qualname: element.qualname,
              screen: screen.qualname,
              range: element.nameRange,
              tooltip:
                (element.kind === "window"
                  ? description
                  : describeLocator(element.locator)) +
                "\n" +
                screen.file +
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
          id: discovery.root + "|" + screen.id,
          label: screen.name,
          description: path.relative(discovery.root, screen.file),
          kind: "screen" as const,
          icon: "symbol-class",
          children,
          file: screen.file,
          range: screen.nameRange,
          screen: screen.qualname,
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
            children: screens,
          },
        ]
      : screens;
  });
}
