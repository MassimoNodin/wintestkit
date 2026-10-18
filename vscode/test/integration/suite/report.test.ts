import * as assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";

suite("Report preview", () => {
  test("opens the HTML report inside VS Code and reuses its panel", async function () {
    this.timeout(60000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    const dir = mkdtempSync(path.join(tmpdir(), "wtk-report-"));
    mkdirSync(path.join(dir, "artifacts"));
    const file = path.join(dir, "index.html");
    writeFileSync(file, "<!doctype html><html><head><title>r</title></head><body><img src='artifacts/a.png'></body></html>");
    await api.reports.preview(file);
    const reportTabs = () =>
      vscode.window.tabGroups.all
        .flatMap((group) => group.tabs)
        .filter((entry) => entry.label === "WinTestKit Report");
    // The tab model updates a moment after the panel is created.
    for (let attempt = 0; attempt < 40 && reportTabs().length === 0; attempt++)
      await new Promise((resolve) => setTimeout(resolve, 100));
    const tab = reportTabs()[0];
    assert.ok(
      tab,
      "a report tab is open; tabs: " +
        vscode.window.tabGroups.all.flatMap((group) => group.tabs.map((entry) => entry.label)).join(", "),
    );
    assert.ok(tab.input instanceof vscode.TabInputWebview);
    assert.ok(tab.input.viewType.endsWith("wintestkit.report"));
    // Previewing again reuses the same panel instead of opening another.
    await api.reports.preview(file);
    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(reportTabs().length, 1);
  });

  test("a failed run opens the report straight away in the active editor group", async function () {
    this.timeout(60000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    for (const group of vscode.window.tabGroups.all)
      await vscode.window.tabGroups.close(group.tabs.filter((entry) => entry.label === "WinTestKit Report"));
    const dir = mkdtempSync(path.join(tmpdir(), "wtk-report-"));
    const file = path.join(dir, "index.html");
    writeFileSync(file, "<!doctype html><html><head></head><body>failed</body></html>");
    let project = api.elements.projects.all[0];
    for (let attempt = 0; attempt < 40 && !project; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      project = api.elements.projects.all[0];
    }
    assert.ok(project, "the example project is found");
    api.reports.record(project, file, 2, 1);
    let tab: vscode.Tab | undefined;
    for (let attempt = 0; attempt < 60 && !tab; attempt++) {
      tab = vscode.window.tabGroups.all.flatMap((group) => group.tabs).find((entry) => entry.label === "WinTestKit Report");
      if (!tab) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(tab, "the report opened without clicking anything");
    assert.ok(tab.isActive, "and it is the visible tab");
    assert.equal(tab.group.viewColumn, vscode.window.tabGroups.activeTabGroup.viewColumn);
  });

  test("waits for a report that the run announces before it is written", async function () {
    this.timeout(60000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    for (const group of vscode.window.tabGroups.all)
      await vscode.window.tabGroups.close(group.tabs.filter((entry) => entry.label === "WinTestKit Report"));
    const dir = mkdtempSync(path.join(tmpdir(), "wtk-report-"));
    const file = path.join(dir, "index.html");
    const project = api.elements.projects.all[0];
    assert.ok(project);
    api.reports.record(project, file, 1, 0); // announced, but not on disk yet
    await new Promise((resolve) => setTimeout(resolve, 800));
    assert.equal(
      vscode.window.tabGroups.all.flatMap((group) => group.tabs).some((entry) => entry.label === "WinTestKit Report"),
      false,
    );
    writeFileSync(file, "<!doctype html><html><head></head><body>late</body></html>");
    let opened = false;
    for (let attempt = 0; attempt < 60 && !opened; attempt++) {
      opened = vscode.window.tabGroups.all.flatMap((group) => group.tabs).some((entry) => entry.label === "WinTestKit Report");
      if (!opened) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(opened, "the report opened once it was written");
  });
});
