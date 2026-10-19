import * as assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";

suite("Clear test results", () => {
  test("native clearing removes retained reports without a live TestRun and still clears other providers", async function () {
    this.timeout(60000);
    const api = await vscode.extensions.getExtension("wintestkit.wintestkit")!.activate();
    let project = api.elements.projects.all[0];
    for (let attempt = 0; !project && attempt < 100; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      project = api.elements.projects.all[0];
    }
    assert.ok(project, "workspace project is available");
    for (let attempt = 0; !api.tests.items.size && attempt < 100; attempt++)
      await new Promise((resolve) => setTimeout(resolve, 100));
    const item = [...api.tests.items.values()][0] as vscode.TestItem;
    assert.ok(item, "a discovered test item is available");
    const nodeid = item.id.slice(item.id.indexOf("|") + 1);
    const root = mkdtempSync(path.join(tmpdir(), "wtk-clear-results-"));
    const directory = path.join(root, "runs", "retained");
    mkdirSync(directory, { recursive: true });
    writeFileSync(path.join(directory, "results.json"), JSON.stringify({ version: 1, tests: [{ id: nodeid }] }));
    mkdirSync(path.join(directory, "artifacts"));
    writeFileSync(path.join(directory, "artifacts", "frame.webp"), "frame");
    const name = api.reports.history.newName();
    api.reports.history.start(name, project.root.toString(), "retained", directory);
    api.reports.history.finish(name, project.root.toString(), { failed: 0, passed: 1 });
    for (let attempt = 0; !item.tags.some((tag) => tag.id === "wintestkit.reportAvailable") && attempt < 50; attempt++)
      await new Promise((resolve) => setTimeout(resolve, 100));
    assert.equal(item.tags.some((tag) => tag.id === "wintestkit.reportAvailable"), true);
    api.reports.record(project, path.join(directory, "index.html"), 0, 1);
    await api.reports.preview(path.join(directory, "index.html"));
    const other = vscode.tests.createTestController("wtk-clear-regression", "Other provider");
    const run = other.createTestRun(new vscode.TestRunRequest());
    let disposed = false;
    run.onDidDispose(() => { disposed = true; });
    run.end();
    try {
      await vscode.commands.executeCommand("testing.clearTestResults");
      for (let attempt = 0; !disposed && attempt < 50; attempt++)
        await new Promise((resolve) => setTimeout(resolve, 100));
      assert.equal(disposed, true, "the original built-in clear still runs");
      assert.equal(existsSync(directory), false, "report and replay artifacts are deleted");
      assert.equal(api.reports.history.get(name), undefined);
      assert.equal(api.reports.lastRun(project), undefined);
      assert.equal(item.tags.some((tag) => tag.id === "wintestkit.reportAvailable"), false);
      for (let attempt = 0; attempt < 50 && vscode.window.tabGroups.all.some((group) =>
        group.tabs.some((tab) => tab.label === "WinTestKit Report")); attempt++)
        await new Promise((resolve) => setTimeout(resolve, 100));
      assert.equal(vscode.window.tabGroups.all.some((group) =>
        group.tabs.some((tab) => tab.label === "WinTestKit Report")), false);
      const second = api.reports.history.newName();
      mkdirSync(directory, { recursive: true });
      writeFileSync(path.join(directory, "results.json"), JSON.stringify({ version: 1, tests: [] }));
      api.reports.history.start(second, project.root.toString(), "retained", directory);
      await vscode.commands.executeCommand("testing.clearTestResults");
      assert.equal(existsSync(directory), false, "subsequent clicks still clear reports");
    } finally {
      other.dispose();
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("clear snapshots protect active runs, future runs and unrelated workspaces", async () => {
    const api = await vscode.extensions.getExtension("wintestkit.wintestkit")!.activate();
    const project = api.elements.projects.all[0];
    assert.ok(project);
    const root = mkdtempSync(path.join(tmpdir(), "wtk-clear-snapshot-"));
    const add = (key: string) => {
      const name = api.reports.history.newName();
      const directory = path.join(root, "runs", name.replace(/[^a-z0-9]/gi, "-"));
      mkdirSync(directory, { recursive: true });
      writeFileSync(path.join(directory, "results.json"), JSON.stringify({ version: 1, tests: [] }));
      api.reports.history.start(name, key, "test", directory);
      return { name, directory };
    };
    const completed = add(project.root.toString());
    const active = add(project.root.toString());
    const elsewhere = add("file:///another-workspace");
    api.tests.activeRunNames.add(active.name);
    const clear = api.tests.prepareClearResults();
    api.tests.activeRunNames.delete(active.name);
    const future = add(project.root.toString());
    try {
      await clear();
      assert.equal(existsSync(completed.directory), false);
      for (const entry of [active, elsewhere, future])
        assert.equal(existsSync(entry.directory), true);
    } finally {
      for (const entry of [active, elsewhere, future]) await api.reports.history.discard(entry.name);
      rmSync(root, { recursive: true, force: true });
    }
  });
});
