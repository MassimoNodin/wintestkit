import type {
  DefinitionError,
  DefinitionMatch,
  InspectPropertiesResult,
  NodeCoverage,
  NodeInfo,
  Suggestion,
} from "../protocol/generated";
import type { TourView } from "../setup/tour";
import type { ObjectPreview } from "./objectPreviews";

export const SPY_TOUR_ACTIONS = ["back", "next", "close", "disable", "skip", "finish"] as const;

export type SpyRequest =
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
      type: "expand" | "select" | "highlight" | "loadProperties";
      nodeId: string;
    }
  | { type: "copy"; text: string }
  | { type: "openDefinition"; id: string };
export type SpyResponse =
  | { type: "savedDefinition"; id: string; qualname: string; preview?: ObjectPreview; reason?: string }
  | { type: "objectPreview"; nodeId: string; preview?: ObjectPreview; reason?: string }
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
      hasProject: boolean;
      showOtherApps: boolean;
      bringToFront: boolean;
    }
  | { type: "roots"; nodes: NodeInfo[] }
  | { type: "children"; nodeId: string; nodes: NodeInfo[]; expanded?: boolean }
  | {
      type: "selected";
      nodeId: string;
      properties: InspectPropertiesResult;
      suggestion?: Suggestion;
    }
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
  if (
    ["expand", "select", "highlight", "loadProperties"].includes(
      String(message.type),
    ) &&
    typeof message.nodeId === "string" &&
    message.nodeId.length <= 512
  )
    return {
      type: message.type as
        "expand" | "select" | "highlight" | "loadProperties",
      nodeId: message.nodeId,
    };
  if (
    message.type === "copy" &&
    typeof message.text === "string" &&
    message.text.length <= 100000
  )
    return { type: "copy", text: message.text };
  if (
    message.type === "openDefinition" &&
    typeof message.id === "string" &&
    message.id.length <= 2048
  )
    return { type: "openDefinition", id: message.id };
}
