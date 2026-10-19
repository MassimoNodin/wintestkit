import { readFileSync } from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";

const manifest = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../package.json"), "utf8"),
);
const controllerSource = readFileSync(
  path.resolve(__dirname, "../../src/testing/controller.ts"),
  "utf8",
);

describe("report button on the Test Results rows", () => {
  const entries = manifest.contributes.menus["testing/item/result"];

  it("offers Open in Report on WinTestKit Test Explorer rows with source locations", () => {
    expect(manifest.contributes.menus["testing/item/context"]).toContainEqual({
      command: "wintestkit.openTestReport",
      when: "controllerId == wintestkit && testing.testItemHasUri && testId in wintestkit.reportTestIds",
      group: "inline@9",
    });
    expect(manifest.contributes.commands.some((command: { command: string }) =>
      command.command === "wintestkit.openTestReport")).toBe(true);
  });

  it("offers an inline button only on WinTestKit's test rows", () => {
    const entry = entries.find((item: { when: string }) =>
      item.when.includes("peekItemType == test"),
    );
    expect(entry.command).toBe("wintestkit.openRunReport");
    expect(entry.group).toMatch(/^inline/);
    const id = /createTestController\(\s*"([^"]+)"/.exec(controllerSource)?.[1];
    expect(id).toBe("wintestkit");
    expect(entry.when).toContain(`controllerId == ${id}`);
    expect(entry.when).toContain("peekItemType == test");
    expect(entries.every((item: { when: string }) => item.when.includes("controllerId == wintestkit"))).toBe(true);
  });

  it("uses commands that exist, with the row command kept out of the palette", () => {
    const commands = manifest.contributes.commands.map(
      (command: { command: string }) => command.command,
    );
    expect(commands).toContain("wintestkit.openRunReport");
    expect(commands).toContain("wintestkit.openPreviousReport");
    const hidden = manifest.contributes.menus.commandPalette.find(
      (item: { command: string }) =>
        item.command === "wintestkit.openRunReport",
    );
    expect(hidden.when).toBe("false");
  });

  it("has a setting for how many runs keep their report", () => {
    const setting =
      manifest.contributes.configuration.properties[
        "wintestkit.keepRunReports"
      ];
    expect(setting).toMatchObject({ type: "number", default: 20, minimum: 1 });
  });
});
