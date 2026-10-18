import type {
  DefinitionError,
  DefinitionMatch,
  InspectPropertiesResult,
  NodeCoverage,
  NodeInfo,
  Suggestion,
} from "../protocol/generated";

export type SpyRequest =
  | {
      type: "pick" | "stopPick" | "refresh" | "addToPage";
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
  | { type: "rootIcons"; icons: Record<string, string> }
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
      hasProject: boolean;
      showOtherApps: boolean;
      bringToFront: boolean;
    }
  | { type: "roots"; nodes: NodeInfo[] }
  | { type: "children"; nodeId: string; nodes: NodeInfo[] }
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
      suggestion: Suggestion;
      ancestors: NodeInfo[];
    }
  | { type: "error"; message: string };

export function parseSpyRequest(value: unknown): SpyRequest | undefined {
  if (!value || typeof value !== "object") return;
  const message = value as Record<string, unknown>;
  if (message.type === "ready")
    return typeof message.showOtherApps === "boolean"
      ? { type: "ready", showOtherApps: message.showOtherApps }
      : { type: "ready" };
  if (message.type === "showOtherApps" || message.type === "bringToFront")
    return typeof message.enabled === "boolean"
      ? { type: message.type, enabled: message.enabled }
      : undefined;
  if (
    ["pick", "stopPick", "refresh", "addToPage"].includes(String(message.type))
  )
    return {
      type: message.type as "pick" | "stopPick" | "refresh" | "addToPage",
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

export function suggestionText(suggestion: Suggestion): string {
  return [
    ...suggestion.helpers.map(
      (helper) => helper.attributeName + " = " + helper.code,
    ),
    suggestion.attributeName + " = " + suggestion.code,
  ].join("\n");
}
