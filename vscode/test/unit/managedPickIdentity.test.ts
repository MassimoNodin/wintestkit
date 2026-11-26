import { describe, expect, it } from "vitest";
import type { NodeInfo } from "../../src/protocol/generated";
import { matchManagedIdentity } from "../../src/spy/selectionPath";
const node = (id: string, xName?: string, siblingIndex?: number): NodeInfo => ({
  nodeId: id, hasChildren: false, source: "wpf", identity: { type: "System.Windows.Controls.Button", xName, siblingIndex },
  info: { controlType: "Button", className: "Button", automationId: "", name: "", frameworkId: "WPF", processId: 1, rect: null, isEnabled: true, isOffscreen: false, hasKeyboardFocus: false, runtimeId: id },
});
describe("managed pick identity", () => {
  it("matches recreated nodes by xName", () => {
    expect(matchManagedIdentity(node("old", "Save"), [node("one", "Cancel"), node("two", "Save")])?.node.nodeId).toBe("two");
  });
  it("distinguishes same-type siblings by index", () => {
    expect(matchManagedIdentity(node("old", undefined, 1), [node("one", undefined, 0), node("two", undefined, 1)])?.node.nodeId).toBe("two");
  });
  it("leaves an ambiguous level unresolved", () => {
    expect(matchManagedIdentity(node("old"), [node("one"), node("two")])).toBeUndefined();
  });
});
