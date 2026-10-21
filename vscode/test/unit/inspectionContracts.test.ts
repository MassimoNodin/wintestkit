import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import type {
  InspectionProperty,
  InspectPartialErrorData,
  InspectRefreshParams,
  InspectRefreshResult,
  SpyPickedNotification,
} from "../../src/protocol/generated";

const inspection = {
  name: "UIA values",
  typeName: "list",
  kind: "array",
  children: [
    { name: "0", typeName: "str", kind: "scalar", value: "Sign in" },
    { name: "1", typeName: "NoneType", kind: "scalar", value: null },
    { name: "2", typeName: "UIA", kind: "unavailable", status: "Provider unavailable" },
    { name: "3", typeName: "IUnknown", kind: "object", status: "Opaque external UIA value" },
  ],
} satisfies InspectionProperty;

it("shares bounded external UIA property examples with Python", () => {
  const fixture = JSON.parse(readFileSync(
    resolve(__dirname, "../../../python/tests/contract/fixtures/inspection-property.json"), "utf8",
  ));
  expect(inspection).toEqual(fixture);
});

it("retains optional identity-first picks and legacy tree result contracts", () => {
  const params = { includeOtherApps: true, foregroundForProcessId: 123 } satisfies InspectRefreshParams;
  const refresh = {
    nodes: [], status: { running: true, pids: [123], owned: false },
  } satisfies InspectRefreshResult;
  const partial = {
    nodes: [], complete: false, errors: [{ index: 1, message: "Stale sibling" }],
  } satisfies InspectPartialErrorData;
  const picked: Pick<SpyPickedNotification, "sessionId"> = { sessionId: "picker-2" };
  expect(params.includeOtherApps).toBe(true);
  expect(refresh.status.pids).toEqual([123]);
  expect(partial.complete).toBe(false);
  expect(picked.sessionId).toBe("picker-2");
});
