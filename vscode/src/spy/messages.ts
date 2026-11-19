import type {
  DefinitionError,
  DefinitionMatch,
  InspectPropertiesResult,
  NodeCoverage,
  NodeInfo,
  Suggestion,
} from "../protocol/generated";
import type { TourView } from "../setup/tour";
import { MAX_PREVIEW_DATA_URL, type PreviewImages } from "./objectPreviews";
import { parseSelectionPath, type PathSegment } from "./selectionPath";

/** A UI Automation property name, as listed under All properties. */
export const PROPERTY_NAME = /^[A-Za-z][A-Za-z0-9]{0,63}$/;
export const MAX_SHOWN_PROPERTIES = 64;

export const SPY_TOUR_ACTIONS = ["back", "next", "close", "disable", "skip", "finish"] as const;

export type ManagedRequest =
  | { type: "managedInvoke"; memberKey: string; arguments: { kind: string; text: string }[] }
  | { type: "managedAttach" | "managedDetach" | "managedRefresh" }
  | { type: "managedRead" | "managedExpand"; memberKey: string; scope?: string }
  | { type: "managedLoadMore"; group: string }
  | { type: "managedMethods"; action: "activate" | "deactivate" | "retry" | "more" }
  | { type: "managedReadVisible"; memberKeys: string[]; scopes?: string[] }
  | { type: "managedCopy"; kind: "value" | "path" | "locator" | "export"; memberKey?: string; scope?: string };

export type SpyRequest =
  | ManagedRequest
  | { type: "showProperties" | "propertiesReady" | "upgradePackage" | "selectionRemoved" | "retryPreview" }
  | { type: "expandedPaths"; paths: PathSegment[][] }
  | { type: "refreshChildren"; nodeId: string; revision: number }
  | { type: "refreshCounts"; added: number; removed: number; kept: number; redrawn: number }
  | { type: "treeAttach"; nodeId: string }
  | { type: "treeMore"; nodeId: string; pageToken: string }
  | { type: "tour"; action: (typeof SPY_TOUR_ACTIONS)[number] }
  | {
      type: "pick" | "stopPick" | "refresh" | "addToPage" | "chooseApp";
    }
  | {
      type: "ready";
      showOtherApps?: boolean;
    }
  | {
      type: "showOtherApps" | "bringToFront";
      enabled: boolean;
    }
  | {
      type: "expand" | "highlight" | "loadProperties";
      nodeId: string;
    }
  /** `path` is the route from a root window, so the selection can be found again after a reload. */
  | { type: "select"; nodeId: string; path?: PathSegment[] }
  | { type: "copy"; text: string }
  | { type: "generateLocator"; nodeId: string }
  | { type: "pinProperty"; name: string; pinned: boolean }
  | { type: "openPreview"; view: "element" | "window"; dataUrl: string }
  | { type: "openDefinition"; id: string };
export type SpyResponse =
  | { type: "compatibilityBlocked"; message: string; label: string }
  | { type: "propertiesVisibility"; visible: boolean }
  | { type: "selectionCleared" }
  | { type: "selectionPending"; nodeId: string }
  | { type: "wpfDetails"; nodeId: string; missing: boolean; blocked?: { code: string; hint: string } }
  | { type: "objectPreview"; nodeId: string; preview?: PreviewImages; reason?: string }
  | { type: "selectionRestored"; nodeId: string }
  | { type: "enumerationIncomplete"; message: string; nodeId?: string }
  | { type: "rootIcons"; icons: Record<string, string> }
  /** The guided tour is showing: dull the panel, and light Pick element when it is the subject. */
  | { type: "tour"; dim: boolean; spyLit: boolean; tutorial?: TourView }
  | {
      type: "progress";
      taskId: number;
      title: string;
      phase: string;
      completed: number;
      total: number;
      done: boolean;
      target: "tree" | "details";
      failed: boolean;
      nodeId?: string;
    }
  | {
      type: "state";
      picking: boolean;
      appRunning: boolean;
      targetName: string;
      /** The selected application's name and processes: its root windows are marked in the tree. */
      appName?: string;
      appPids?: number[];
      hasProject: boolean;
      showOtherApps: boolean;
      bringToFront: boolean;
      /** Properties the user pinned to the default list (a user setting). */
      shownProperties?: string[];
      showRefreshCounts?: boolean;
    }
  | { type: "roots"; nodes: NodeInfo[] }
  | { type: "rootsDiff"; nodes: NodeInfo[]; revision: number; refresh?: boolean }
  | { type: "childrenDiff"; nodeId: string; nodes: NodeInfo[]; revision: number; nextPageToken?: string; blocked?: { code: string; hint: string } }
  | { type: "children"; nodeId: string; nodes: NodeInfo[]; expanded?: boolean; append?: boolean; nextPageToken?: string; blocked?: { code: string; hint: string } }
  | {
      type: "selected";
      nodeId: string;
      properties: InspectPropertiesResult;
      suggestion?: Suggestion;
    }
  | { type: "suggestionLoading"; nodeId: string }
  | { type: "suggestion"; nodeId: string; suggestion: Suggestion }
  | { type: "suggestionUnavailable"; nodeId: string; reason: string }
  | {
      type: "definitions";
      nodeId: string;
      state: "loading" | "ready" | "unavailable";
      definitions?: DefinitionMatch[];
      errors?: DefinitionError[];
      pageCount?: number;
      appRunning?: boolean;
      reason?: string;
    }
  | {
      // Nodes in ``nodeIds`` are settled: those missing from ``covered`` are not defined anywhere.
      type: "coverage";
      nodeIds: string[];
      covered: Record<string, NodeCoverage>;
    }
  | {
      type: "allProperties";
      nodeId: string;
      properties: InspectPropertiesResult;
    }
  | { type: "propertiesLoading"; nodeId: string; loading: boolean }
  | { type: "hover"; node: NodeInfo }
  | {
      type: "picked";
      node: NodeInfo;
      suggestion?: Suggestion;
      ancestors: NodeInfo[];
    }
  | { type: "error"; message: string };

export function parseSpyRequest(value: unknown): SpyRequest | undefined {
  if (!value || typeof value !== "object") return;
  const message = value as Record<string, unknown>;
  if (message.type === "refreshChildren" && typeof message.nodeId === "string" && message.nodeId.length > 0 && message.nodeId.length <= 512 && Number.isSafeInteger(message.revision)) return { type: "refreshChildren", nodeId: message.nodeId, revision: message.revision as number };
  if (message.type === "refreshCounts" && [message.added, message.removed, message.kept, message.redrawn].every((n) => Number.isSafeInteger(n) && (n as number) >= 0)) return { type: "refreshCounts", added: message.added as number, removed: message.removed as number, kept: message.kept as number, redrawn: message.redrawn as number };
  if (message.type === "expandedPaths" && Array.isArray(message.paths) && message.paths.length <= 200) {
    const paths = message.paths.map(parseSelectionPath);
    if (paths.every((path): path is PathSegment[] => !!path)) return { type: "expandedPaths", paths };
    return;
  }
  if ((message.type === "treeAttach" || message.type === "treeMore") && typeof message.nodeId === "string" && message.nodeId.length > 0 && message.nodeId.length <= 512) {
    if (message.type === "treeAttach") return { type: "treeAttach", nodeId: message.nodeId };
    if (typeof message.pageToken === "string" && message.pageToken.length > 0 && message.pageToken.length <= 128) return { type: "treeMore", nodeId: message.nodeId, pageToken: message.pageToken };
  }
  if (typeof message.type === "string" && message.type.startsWith("managed")) return parseManagedRequest(message);
  if (message.type === "tour")
    return SPY_TOUR_ACTIONS.includes(message.action as (typeof SPY_TOUR_ACTIONS)[number])
      ? { type: "tour", action: message.action as (typeof SPY_TOUR_ACTIONS)[number] }
      : undefined;
  if (message.type === "showProperties" || message.type === "propertiesReady" || message.type === "upgradePackage" || message.type === "selectionRemoved" || message.type === "retryPreview") return { type: message.type };
  if (message.type === "ready")
    return typeof message.showOtherApps === "boolean"
      ? { type: "ready", showOtherApps: message.showOtherApps }
      : { type: "ready" };
  if (message.type === "showOtherApps" || message.type === "bringToFront")
    return typeof message.enabled === "boolean"
      ? { type: message.type, enabled: message.enabled }
      : undefined;
  if (
    ["pick", "stopPick", "refresh", "addToPage", "chooseApp"].includes(String(message.type))
  )
    return {
      type: message.type as "pick" | "stopPick" | "refresh" | "addToPage" | "chooseApp",
    };
  if (message.type === "select" && typeof message.nodeId === "string" && message.nodeId.length <= 512) {
    const path = parseSelectionPath(message.path);
    return path
      ? { type: "select", nodeId: message.nodeId, path }
      : { type: "select", nodeId: message.nodeId };
  }
  if (
    ["expand", "highlight", "loadProperties", "generateLocator"].includes(
      String(message.type),
    ) &&
    typeof message.nodeId === "string" &&
    message.nodeId.length <= 512
  )
    return {
      type: message.type as
        "expand" | "highlight" | "loadProperties" | "generateLocator",
      nodeId: message.nodeId,
    };
  if (
    message.type === "copy" &&
    typeof message.text === "string" &&
    message.text.length <= 100000
  )
    return { type: "copy", text: message.text };
  if (
    message.type === "pinProperty" &&
    typeof message.name === "string" &&
    PROPERTY_NAME.test(message.name) &&
    typeof message.pinned === "boolean"
  )
    return { type: "pinProperty", name: message.name, pinned: message.pinned };
  if (
    message.type === "openPreview" &&
    (message.view === "element" || message.view === "window") &&
    typeof message.dataUrl === "string" &&
    message.dataUrl.startsWith("data:image/webp;base64,") &&
    message.dataUrl.length <= MAX_PREVIEW_DATA_URL
  )
    return { type: "openPreview", view: message.view, dataUrl: message.dataUrl };
  if (
    message.type === "openDefinition" &&
    typeof message.id === "string" &&
    message.id.length <= 2048
  )
    return { type: "openDefinition", id: message.id };
}

/** Managed messages have a closed shape; identities always come from the host. */
export function parseManagedRequest(message: Record<string, unknown>): ManagedRequest | undefined {
  const keys = Object.keys(message);
  const exact = (...allowed: string[]) => keys.length === allowed.length && keys.every((key) => allowed.includes(key));
  const key = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 1024;
  if (message.type === "managedInvoke" && exact("type", "memberKey", "arguments") && typeof message.memberKey === "string" && message.memberKey.length > 0 && message.memberKey.length <= 8192 && Array.isArray(message.arguments) && message.arguments.length <= 16 && message.arguments.every((arg) => arg && typeof arg === "object" && !Array.isArray(arg) && Object.keys(arg).length === 2 && typeof arg.kind === "string" && typeof arg.text === "string" && arg.text.length <= 4096)) return { type: "managedInvoke", memberKey: message.memberKey, arguments: message.arguments as { kind: string; text: string }[] };
  if ((message.type === "managedAttach" || message.type === "managedDetach" || message.type === "managedRefresh") && exact("type")) return { type: message.type };
  if ((message.type === "managedRead" || message.type === "managedExpand") && (exact("type", "memberKey") || (exact("type", "memberKey", "scope") && key(message.scope))) && key(message.memberKey)) return { type: message.type, memberKey: message.memberKey, ...(typeof message.scope === "string" ? { scope: message.scope } : {}) };
  if (message.type === "managedLoadMore" && exact("type", "group") && key(message.group)) return { type: message.type, group: message.group };
  if (message.type === "managedMethods" && exact("type", "action") && (message.action === "activate" || message.action === "deactivate" || message.action === "retry" || message.action === "more")) return { type: message.type, action: message.action };
  if (message.type === "managedReadVisible" && (exact("type", "memberKeys") || (exact("type", "memberKeys", "scopes") && Array.isArray(message.scopes) && message.scopes.every((scope) => scope === "" || key(scope)))) && Array.isArray(message.memberKeys) && message.memberKeys.length > 0 && message.memberKeys.length <= 32 && message.memberKeys.every(key) && (!Array.isArray(message.scopes) || message.scopes.length === message.memberKeys.length)) return { type: message.type, memberKeys: message.memberKeys, ...(Array.isArray(message.scopes) ? { scopes: message.scopes as string[] } : {}) };
  if (message.type === "managedCopy" && (exact("type", "kind") || (exact("type", "kind", "memberKey") && key(message.memberKey)) || (exact("type", "kind", "memberKey", "scope") && key(message.memberKey) && key(message.scope))) && (message.kind === "value" || message.kind === "path" || message.kind === "locator" || message.kind === "export")) return { type: message.type, kind: message.kind, ...(typeof message.memberKey === "string" ? { memberKey: message.memberKey } : {}), ...(typeof message.scope === "string" ? { scope: message.scope } : {}) };
}
