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
  | { type: "managedAttach" | "managedDetach" | "managedRefresh" }
  | { type: "managedRead" | "managedExpand"; memberKey: string }
  | { type: "managedLoadMore"; group: string }
  | { type: "managedReadVisible"; memberKeys: string[] }
  | { type: "managedCopy"; kind: "value" | "path" | "locator" | "export"; memberKey?: string };

export type SpyRequest =
  | ManagedRequest
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
    }
  | { type: "roots"; nodes: NodeInfo[] }
  | { type: "children"; nodeId: string; nodes: NodeInfo[]; expanded?: boolean }
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
  if (typeof message.type === "string" && message.type.startsWith("managed")) return parseManagedRequest(message);
  if (message.type === "tour")
    return SPY_TOUR_ACTIONS.includes(message.action as (typeof SPY_TOUR_ACTIONS)[number])
      ? { type: "tour", action: message.action as (typeof SPY_TOUR_ACTIONS)[number] }
      : undefined;
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
  if ((message.type === "managedAttach" || message.type === "managedDetach" || message.type === "managedRefresh") && exact("type")) return { type: message.type };
  if ((message.type === "managedRead" || message.type === "managedExpand") && exact("type", "memberKey") && key(message.memberKey)) return { type: message.type, memberKey: message.memberKey };
  if (message.type === "managedLoadMore" && exact("type", "group") && key(message.group)) return { type: message.type, group: message.group };
  if (message.type === "managedReadVisible" && exact("type", "memberKeys") && Array.isArray(message.memberKeys) && message.memberKeys.length > 0 && message.memberKeys.length <= 32 && message.memberKeys.every(key)) return { type: message.type, memberKeys: message.memberKeys };
  if (message.type === "managedCopy" && (exact("type", "kind") || (exact("type", "kind", "memberKey") && key(message.memberKey))) && (message.kind === "value" || message.kind === "path" || message.kind === "locator" || message.kind === "export")) return { type: message.type, kind: message.kind, ...(typeof message.memberKey === "string" ? { memberKey: message.memberKey } : {}) };
}
