import type { CheckResult } from "../protocol/generated";
import type { ElementNode } from "./elementsTreeModel";

export const SECTIONS = ["pages", "flows"] as const;
export type NavigationSection = (typeof SECTIONS)[number];
export const SECTION_LABEL: Record<NavigationSection, string> = {
  pages: "Page Tree",
  flows: "Flows",
};
export const navigationSectionKey = "wintestkit.navigation.section";
export const navigationExpandedKey = "wintestkit.navigation.expanded";

export type NavigationAction = "highlight" | "check" | "checkPage" | "run";

export const ACTION_PRESENTATION: Record<
  NavigationAction,
  { icon: string; title: string }
> = {
  highlight: { icon: "eye", title: "Highlight Element" },
  check: { icon: "check", title: "Check Element" },
  checkPage: { icon: "check-all", title: "Check all elements in this class exist" },
  run: { icon: "play", title: "Run Flow" },
};

const ACTIONS = new Set<string>(Object.keys(ACTION_PRESENTATION));

export function isSection(value: unknown): value is NavigationSection {
  return value === "pages" || value === "flows";
}

export function readSection(value: unknown): NavigationSection {
  return isSection(value) ? value : "pages";
}

export function readExpanded(
  value: unknown,
): Partial<Record<NavigationSection, string[]>> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const record = value as Record<string, unknown>;
  const expanded: Partial<Record<NavigationSection, string[]>> = {};
  for (const section of SECTIONS) {
    const ids = record[section];
    if (!Array.isArray(ids)) continue;
    expanded[section] = ids
      .filter(
        (id): id is string =>
          typeof id === "string" && id.length > 0 && id.length <= 4096,
      )
      .slice(0, 400);
  }
  return expanded;
}

export function nodeContext(node: ElementNode): string {
  return node.kind;
}

export function actionsFor(node: ElementNode): NavigationAction[] {
  const context = nodeContext(node);
  const actions: NavigationAction[] = [];
  if (
    (context === "element" || context === "window") &&
    node.file &&
    node.qualname
  )
    actions.push("highlight", "check");
  if (context === "page" && node.file && node.page) actions.push("checkPage");
  if (context === "flow" && node.runnable && node.file) actions.push("run");
  return actions;
}

export function menuContext(
  node: ElementNode,
): Record<string, string | boolean> {
  const context: Record<string, string | boolean> = {
    webviewSection: nodeContext(node),
    preventDefaultContextMenuItems: true,
  };
  const section = context.webviewSection;
  if (
    (section === "element" || section === "window") &&
    node.file &&
    node.qualname
  ) {
    context.file = node.file;
    context.qualname = node.qualname;
  }
  if (section === "page" && node.file && node.page) {
    context.file = node.file;
    context.page = node.page;
  }
  if (section === "flow" && node.runnable && node.file) {
    context.file = node.file;
    context.flowName = node.label;
  }
  return context;
}

export function checkPresentation(status: CheckResult["status"] | undefined):
  | {
      icon: "pass" | "warning" | "error";
      color:
        | "testing.iconPassed"
        | "list.warningForeground"
        | "testing.iconFailed";
    }
  | undefined {
  if (!status) return undefined;
  if (status === "found") return { icon: "pass", color: "testing.iconPassed" };
  if (status === "ambiguous")
    return { icon: "warning", color: "list.warningForeground" };
  return { icon: "error", color: "testing.iconFailed" };
}

export function iconColorClass(
  color: NonNullable<ReturnType<typeof checkPresentation>>["color"],
): string {
  return color.replaceAll(".", "-");
}

export interface TreeSource {
  id: string;
  label: string;
  children: readonly TreeSource[];
}

export interface VisibleRow {
  id: string;
  parentId?: string;
  label: string;
  expandable: boolean;
  expanded: boolean;
}

export function visibleRows(
  nodes: readonly TreeSource[],
  expanded: ReadonlySet<string>,
  parentId?: string,
): VisibleRow[] {
  const rows: VisibleRow[] = [];
  for (const node of nodes) {
    const open = expanded.has(node.id) && node.children.length > 0;
    rows.push({
      id: node.id,
      parentId,
      label: node.label,
      expandable: node.children.length > 0,
      expanded: open,
    });
    if (open) rows.push(...visibleRows(node.children, expanded, node.id));
  }
  return rows;
}

export function findNode<T extends { id: string; children: readonly T[] }>(
  nodes: readonly T[],
  id: string,
): T | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findNode(node.children, id);
    if (child) return child;
  }
  return undefined;
}

export interface KeyResult {
  focusId: string;
  expand?: boolean;
  collapse?: boolean;
  open?: boolean;
}

export function treeKeyAction(
  rows: readonly VisibleRow[],
  focusId: string | undefined,
  key: string,
): KeyResult | undefined {
  if (!rows.length) return undefined;
  const index = rows.findIndex((row) => row.id === focusId);
  const current = index >= 0 ? rows[index] : undefined;
  if (key === "Home") return { focusId: rows[0].id };
  if (key === "End") return { focusId: rows[rows.length - 1].id };
  if (key === "ArrowDown") {
    const next = index < 0 ? 0 : Math.min(rows.length - 1, index + 1);
    return { focusId: rows[next].id };
  }
  if (key === "ArrowUp") {
    if (!current) return { focusId: rows[rows.length - 1].id };
    return { focusId: rows[Math.max(0, index - 1)].id };
  }
  if (!current) return undefined;
  if (key === "ArrowRight") {
    if (current.expandable && !current.expanded)
      return { focusId: current.id, expand: true };
    const child = rows[index + 1];
    if (current.expanded && child?.parentId === current.id)
      return { focusId: child.id };
    return undefined;
  }
  if (key === "ArrowLeft") {
    if (current.expandable && current.expanded)
      return { focusId: current.id, collapse: true };
    if (current.parentId) return { focusId: current.parentId };
    return undefined;
  }
  if (key === "Enter") return { focusId: current.id, open: true };
  if (key === " ") {
    if (!current.expandable) return { focusId: current.id, open: true };
    return current.expanded
      ? { focusId: current.id, collapse: true }
      : { focusId: current.id, expand: true };
  }
  return undefined;
}

export function typeaheadIndex(
  rows: readonly { label: string }[],
  fromIndex: number,
  query: string,
): number {
  const needle = query.toLowerCase();
  if (!needle || !rows.length) return -1;
  const start =
    query.length > 1 && fromIndex >= 0
      ? fromIndex
      : fromIndex < 0
        ? 0
        : fromIndex + 1;
  for (let offset = 0; offset < rows.length; offset++) {
    const index = (start + offset) % rows.length;
    if (rows[index].label.toLowerCase().startsWith(needle)) return index;
  }
  return -1;
}

export function segmentKey(
  section: NavigationSection,
  key: string,
): NavigationSection | undefined {
  const index = SECTIONS.indexOf(section);
  if (key === "Home") return SECTIONS[0];
  if (key === "End") return SECTIONS[SECTIONS.length - 1];
  if (key === "ArrowRight") return SECTIONS[(index + 1) % SECTIONS.length];
  if (key === "ArrowLeft")
    return SECTIONS[(index - 1 + SECTIONS.length) % SECTIONS.length];
  return undefined;
}

export class NavigationSession {
  readonly expanded: Record<NavigationSection, Set<string>>;
  readonly focus: Partial<Record<NavigationSection, string>> = {};
  private typed = "";
  private typedAt = 0;
  constructor(
    public section: NavigationSection,
    expanded?: Partial<Record<NavigationSection, string[]>>,
  ) {
    this.expanded = {
      pages: new Set(expanded?.pages ?? []),
      flows: new Set(expanded?.flows ?? []),
    };
  }
  select(section: NavigationSection): void {
    this.section = section;
    this.typed = "";
  }
  toggle(id: string, nodes: readonly TreeSource[]): boolean {
    const node = findNode(nodes, id);
    if (!node?.children.length) return false;
    const open = this.expanded[this.section];
    if (open.has(id)) open.delete(id);
    else open.add(id);
    return true;
  }
  key(
    key: string,
    nodes: readonly TreeSource[],
    now: number,
  ): { open: boolean; changed: boolean } {
    const before = this.signature();
    const rows = visibleRows(nodes, this.expanded[this.section]);
    if (key.length === 1 && key !== " ") {
      if (now - this.typedAt > 700) this.typed = "";
      this.typedAt = now;
      this.typed += key.toLowerCase();
      const from = rows.findIndex((row) => row.id === this.focus[this.section]);
      const match = typeaheadIndex(rows, from, this.typed);
      if (match >= 0) this.focus[this.section] = rows[match].id;
      return { open: false, changed: this.signature() !== before };
    }
    this.typed = "";
    const result = treeKeyAction(rows, this.focus[this.section], key);
    if (!result) return { open: false, changed: false };
    this.focus[this.section] = result.focusId;
    if (result.expand) this.expanded[this.section].add(result.focusId);
    if (result.collapse) this.expanded[this.section].delete(result.focusId);
    return {
      open: result.open === true,
      changed: this.signature() !== before || result.open === true,
    };
  }
  prune(nodes: readonly TreeSource[]): void {
    const ids = new Set<string>();
    const visit = (list: readonly TreeSource[]) => {
      for (const node of list) {
        ids.add(node.id);
        visit(node.children);
      }
    };
    visit(nodes);
    const open = this.expanded[this.section];
    for (const id of open) if (!ids.has(id)) open.delete(id);
    const focused = this.focus[this.section];
    if (focused && !ids.has(focused)) delete this.focus[this.section];
  }
  private signature(): string {
    return (
      (this.focus[this.section] ?? "") +
      "\n" +
      [...this.expanded[this.section]].join("\n")
    );
  }
}

export type NavigationMessage =
  | { type: "ready" | "initialize" }
  | { type: "select"; section: NavigationSection }
  | { type: "segmentKey" | "key"; key: string }
  | { type: "toggle" | "open"; id: string }
  | { type: "action"; action: NavigationAction; id: string };

export function parseNavigationMessage(
  value: unknown,
): NavigationMessage | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return undefined;
  const message = value as Record<string, unknown>;
  if ("command" in message || "commandId" in message) return undefined;
  if (message.type === "ready" || message.type === "initialize")
    return { type: message.type };
  if (message.type === "select" && isSection(message.section))
    return { type: "select", section: message.section };
  if (
    (message.type === "segmentKey" || message.type === "key") &&
    typeof message.key === "string" &&
    message.key.length > 0 &&
    message.key.length <= 20
  )
    return { type: message.type, key: message.key };
  if (
    (message.type === "toggle" || message.type === "open") &&
    isNodeId(message.id)
  )
    return { type: message.type, id: message.id };
  if (
    message.type === "action" &&
    typeof message.action === "string" &&
    ACTIONS.has(message.action) &&
    isNodeId(message.id)
  )
    return {
      type: "action",
      action: message.action as NavigationAction,
      id: message.id,
    };
  return undefined;
}

function isNodeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 4096;
}

export type NavigationEffect =
  | { type: "render"; openId?: string; reveal?: boolean }
  | { type: "initialize" }
  | { type: "action"; action: NavigationAction; id: string };

export function reduceNavigation(
  session: NavigationSession,
  nodes: readonly TreeSource[],
  message: NavigationMessage,
  now: number,
): NavigationEffect | undefined {
  switch (message.type) {
    case "ready":
      return { type: "render" };
    case "initialize":
      return { type: "initialize" };
    case "select":
      session.select(message.section);
      return { type: "render" };
    case "segmentKey": {
      const next = segmentKey(session.section, message.key);
      if (!next || next === session.section) return undefined;
      session.select(next);
      return { type: "render" };
    }
    case "toggle":
      if (!session.toggle(message.id, nodes)) return undefined;
      session.focus[session.section] = message.id;
      return { type: "render" };
    case "key": {
      const outcome = session.key(message.key, nodes, now);
      if (!outcome.changed) return undefined;
      const focus = session.focus[session.section];
      return outcome.open && focus
        ? { type: "render", openId: focus, reveal: true }
        : { type: "render", reveal: true };
    }
    case "open":
      session.focus[session.section] = message.id;
      return { type: "render", openId: message.id };
    case "action":
      session.focus[session.section] = message.id;
      return { type: "action", action: message.action, id: message.id };
    default:
      return undefined;
  }
}

export function emptyMessage(
  section: NavigationSection,
  hasProject: boolean,
  count: number,
): string | undefined {
  if (!hasProject || count > 0) return undefined;
  if (section === "flows")
    return "Add reusable Python functions under flows/ to see them here.";
  return undefined;
}

export interface NavNode extends TreeSource {
  description: string;
  tooltip: string;
  icon: string;
  color?: NonNullable<ReturnType<typeof checkPresentation>>["color"];
  context: Record<string, string | boolean>;
  actions: NavigationAction[];
  children: NavNode[];
}

export function flowPresentation(
  state: "running" | "passed" | "failed",
): { icon: string; color?: "testing.iconPassed" | "testing.iconFailed" } {
  if (state === "running") return { icon: "loading" };
  return state === "passed"
    ? { icon: "pass", color: "testing.iconPassed" }
    : { icon: "error", color: "testing.iconFailed" };
}

export function toNavNodes(
  nodes: readonly ElementNode[],
  statusFor: (elementId: string | undefined) => CheckResult["status"] | undefined,
  flowStateFor: (
    node: ElementNode,
  ) => "running" | "passed" | "failed" | undefined = () => undefined,
): NavNode[] {
  return nodes.map((node) => {
    const flowState = flowStateFor(node);
    const presentation = flowState
      ? flowPresentation(flowState)
      : checkPresentation(statusFor(node.elementId));
    return {
      id: node.id,
      label: node.label,
      description: node.description,
      tooltip: node.tooltip ?? node.description,
      icon: presentation?.icon ?? node.icon,
      color: presentation?.color,
      context: menuContext(node),
      actions: actionsFor(node),
      children: toNavNodes(node.children, statusFor, flowStateFor),
    };
  });
}
