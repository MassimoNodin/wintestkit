import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("first-run walkthrough", () => {
  const manifest = JSON.parse(readFileSync(resolve(process.cwd(), "package.json"), "utf8"));
  const walkthrough = manifest.contributes.walkthroughs.find((entry: { id: string }) => entry.id === "wintestkit.firstRun");
  it("uses the actual choose, add-to-page, check, and run completion events", () => {
    expect(walkthrough.steps).toHaveLength(5);
    expect(walkthrough.steps[0].completionEvents).toContain("onContext:wintestkit.hasChosenApp");
    expect(walkthrough.steps[2].completionEvents).toContain("onCommand:wintestkit.spy.addToPage");
    expect(walkthrough.steps[3].completionEvents).toContain("onCommand:wintestkit.checkElement");
    expect(walkthrough.steps[4].completionEvents).toContain("onCommand:testing.runAll");
    expect(manifest.contributes.commands.map((command: { command: string }) => command.command)).toContain("wintestkit.openGettingStarted");
  });
});
