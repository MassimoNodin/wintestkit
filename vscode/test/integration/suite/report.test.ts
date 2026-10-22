import * as assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import type { ExtensionApi } from "../../../src/extension";

suite("Report preview", () => {
  test("report commands preserve run identity across all arguments, not the latest run", async function () {
    this.timeout(60000);
    const extension = vscode.extensions.getExtension<ExtensionApi>("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    const directory = mkdtempSync(path.join(tmpdir(), "wtk-run-command-"));
    const older = api.reports.history.newName();
    const newer = api.reports.history.newName();
    for (const [name, folder] of [[older, "older"], [newer, "newer"]]) {
      const dir = path.join(directory, folder);
      mkdirSync(dir);
      writeFileSync(path.join(dir, "results.json"), JSON.stringify({ version: 1, tests: [] }));
      api.reports.history.start(name, "file:///report-command-test", "test", dir);
    }
    const preview = api.reports.preview;
    const reportTarget = api.tests.reportTarget;
    const opened: string[] = [];
    const selected: (string | undefined)[] = [];
    api.reports.preview = async (file: string, testId?: string) => { opened.push(file); selected.push(testId); };
    const info = { testRunName: older, controllerId: "wintestkit", resultId: "result", taskId: "task" };
    const invoke = async (...args: unknown[]) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          vscode.commands.executeCommand("wintestkit.openRunReport", ...args),
          new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error("The report command did not resolve its run identity")), 5000);
          }),
        ]);
      } finally {
        clearTimeout(timer);
        await vscode.commands.executeCommand("workbench.action.closeQuickOpen");
      }
    };
    try {
      await invoke(info);
      const item = api.tests.controller.createTestItem("report-command-test", "test");
      await invoke(item, info);
      assert.deepEqual(opened, [path.join(directory, "older", "index.html"), path.join(directory, "older", "index.html")]);
      const testId = 'tests/test_a.py::test_ok[a & b]';
      api.tests.reportTarget = () => ({ project: { name: "test", root: vscode.Uri.parse("file:///report-command-test") }, nodeid: testId });
      await invoke(item, info);
      assert.equal(selected[2], testId);
      assert.equal(opened[2], path.join(directory, "older", "index.html"));
      writeFileSync(path.join(directory, "older", "results.json"), JSON.stringify({ version: 1, tests: [{ id: testId, outcome: "passed" }] }));
      await vscode.commands.executeCommand("wintestkit.openTestReport", item);
      assert.equal(selected[3], testId);
      assert.equal(opened[3], path.join(directory, "older", "index.html"));
    } finally {
      api.reports.preview = preview;
      api.tests.reportTarget = reportTarget;
      await api.reports.history.discard(older);
      await api.reports.history.discard(newer);
    }
  });

  test("opens the HTML report inside VS Code and reuses its panel", async function () {
    this.timeout(60000);
    const extension = vscode.extensions.getExtension<ExtensionApi>("wintestkit.wintestkit");
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
    const extension = vscode.extensions.getExtension<ExtensionApi>("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    for (const group of vscode.window.tabGroups.all)
      await vscode.window.tabGroups.close(group.tabs.filter((entry) => entry.label === "WinTestKit Report"));
    const dir = mkdtempSync(path.join(tmpdir(), "wtk-report-"));
    const file = path.join(dir, "index.html");
    writeFileSync(file, "<!doctype html><html><head></head><body>failed</body></html>");
    let project = api.projects.all[0];
    for (let attempt = 0; attempt < 40 && !project; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      project = api.projects.all[0];
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
    const extension = vscode.extensions.getExtension<ExtensionApi>("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    for (const group of vscode.window.tabGroups.all)
      await vscode.window.tabGroups.close(group.tabs.filter((entry) => entry.label === "WinTestKit Report"));
    const dir = mkdtempSync(path.join(tmpdir(), "wtk-report-"));
    const file = path.join(dir, "index.html");
    const project = api.projects.all[0];
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
