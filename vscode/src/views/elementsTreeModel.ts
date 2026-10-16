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
            // Typed elements (ComboBox, a custom DatePicker, ...) show their type; the generic
            // Element and Elements need no label.
            const typed =
              element.kind !== "window" &&
              element.elementType !== undefined &&
              element.elementType !== "Element" &&
              element.elementType !== "Elements"
                ? element.elementType
                : undefined;
            const locatorText =
              element.kind === "window"
                ? describeWindow(element.locator.window ?? {})
                : describeLocator({
                    ...element.locator,
                    within: undefined,
                    window: undefined,
                  });
            const description = typed
              ? `${typed} · ${locatorText}`.trimEnd()
              : locatorText;
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
                (typed ? typed + ": " : "") +
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
    const entries = new Map(discovery.pages.map((page) => [page.id, page]));
    const templates = new Map(pages.map((page) => [page.id, page]));
    const childIds = new Set(
      discovery.pages.flatMap((page) =>
        (page.children ?? []).map((child) => child.pageId),
      ),
    );
    const represented = new Set<string>();
    const copyElements = (nodes: ElementNode[], instanceId: string): ElementNode[] =>
      nodes.map((node) => ({
        ...node,
        id: instanceId + "|" + node.id,
        children: copyElements(node.children, instanceId),
      }));
    const expandPage = (
      pageId: string,
      instanceId: string,
      ancestors: ReadonlySet<string>,
      memberName?: string,
    ): ElementNode => {
      const entry = entries.get(pageId)!;
      const template = templates.get(discovery.root + "|" + pageId)!;
      represented.add(pageId);
      const lineage = new Set([...ancestors, pageId]);
      const children = instanceId === template.id
        ? [...template.children]
        : copyElements(template.children, instanceId);
      for (const child of entry.children ?? []) {
        if (!entries.has(child.pageId) || lineage.has(child.pageId)) continue;
        children.push(expandPage(
          child.pageId,
          instanceId + "|" + JSON.stringify([child.name, child.pageId]),
          lineage,
          child.name,
        ));
      }
      return {
        ...template,
        id: instanceId,
        label: memberName ? memberName + ": " + entry.name : template.label,
        children,
      };
    };
    const roots = pages
      .filter((page) => !childIds.has(page.id.slice(discovery.root.length + 1)))
      .map((page) => expandPage(
        page.id.slice(discovery.root.length + 1), page.id, new Set(),
      ));
    for (const page of pages) {
      const pageId = page.id.slice(discovery.root.length + 1);
      if (!represented.has(pageId))
        roots.push(expandPage(pageId, page.id, new Set()));
    }
    return discoveries.length > 1
      ? [
          {
            id: discovery.root,
            label: path.basename(discovery.root),
            description: discovery.root,
            kind: "project" as const,
            icon: "root-folder",
            children: roots,
          },
        ]
      : roots;
  });
}
