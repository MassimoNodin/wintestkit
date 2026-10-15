import type {
  InspectPropertiesResult,
  NodeInfo,
  Suggestion,
} from "../protocol/generated";

export type SpyRequest =
  | {
      type:
        "ready" | "pick" | "stopPick" | "refresh" | "launchApp" | "addToPage";
    }
  | {
      type: "expand" | "select" | "highlight" | "loadProperties";
      nodeId: string;
    }
  | { type: "copy"; text: string };
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
  if (
    ["ready", "pick", "stopPick", "refresh", "launchApp", "addToPage"].includes(
      String(message.type),
    )
  )
    return {
      type: message.type as
        "ready" | "pick" | "stopPick" | "refresh" | "launchApp" | "addToPage",
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
}

export function suggestionText(suggestion: Suggestion): string {
  return [
    ...suggestion.helpers.map(
      (helper) => helper.attributeName + " = " + helper.code,
    ),
    suggestion.attributeName + " = " + suggestion.code,
  ].join("\n");
}
