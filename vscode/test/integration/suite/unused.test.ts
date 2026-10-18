import * as assert from "node:assert/strict";
import * as vscode from "vscode";

interface ScanApi {
  scan(): Promise<{ cancelled: boolean; capped: boolean; unavailable: number }>;
  has(project: unknown, elementId: string): boolean;
  hasResult(project: unknown): boolean;
  count: number;
}

suite("Unused definitions", () => {
  test("flags Calculator definitions that the Python language server finds no references for", async function () {
    this.timeout(240000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const api = await extension.activate();
    const unused = api.unused as ScanApi;
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder);
    await vscode.commands.executeCommand("wintestkit.elements.refresh");
    let project: unknown;
    let pages: Array<{ qualname: string; elements: Array<{ id: string; name: string }> }> = [];
    for (let attempt = 0; attempt < 120 && pages.length === 0; attempt++) {
      project = api.elements.projects.all[0];
      const result = project ? api.elements.discovery.get(project) : undefined;
      pages = result?.pages ?? [];
      if (pages.length === 0) await new Promise((resolve) => setTimeout(resolve, 500));
    }
    assert.ok(pages.length > 0, "discovery returned pages");
    // Pylance answers reference requests only once it has analysed the workspace.
    // A discovery refresh or edit during a scan cancels it, so wait for things to settle and retry.
    let summary = await unused.scan();
    for (let attempt = 0; attempt < 20 && (summary.cancelled || summary.unavailable > 0); attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      summary = await unused.scan();
    }
    const flagged = pages.flatMap((page) =>
      page.elements
        .filter((element) => unused.has(project, element.id))
        .map((element) => page.qualname + "." + element.name),
    );
    console.log("scan summary", JSON.stringify(summary), "unused:", flagged.join(", "));
    assert.equal(summary.cancelled, false);
    assert.equal(summary.unavailable, 0, "every definition got an answer from the language server");
    assert.ok(unused.hasResult(project));
    assert.equal(unused.count, flagged.length);
    for (const implicit of ["window", "root"])
      assert.ok(!flagged.some((name) => name.endsWith("." + implicit)), "implicit " + implicit + " is never flagged");
    for (const name of ["StandardOperators.divide", "DisplayControls.backspace", "RadixSelection.octal"])
      assert.ok(flagged.includes(name), name + " has no references");
    for (const name of ["StandardOperators.plus", "RadixSelection.binary", "RadixSelection.hexadecimal"])
      assert.ok(!flagged.includes(name), name + " is referenced");
    const numberPad = pages.find((page) => page.qualname === "NumberPad");
    const zero = numberPad?.elements.find((element) => element.name === "zero");
    assert.ok(zero, "NumberPad.zero is discovered");
    assert.equal(unused.has(project, zero.id), false, "NumberPad.zero is used by NumberPad.enter");
  });
});
