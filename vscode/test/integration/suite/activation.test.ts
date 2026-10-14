import * as assert from "node:assert/strict";
import * as vscode from "vscode";
import * as path from "node:path";
import { readFileSync } from "node:fs";

suite("WinTestKit activation", () => {
  test("activates and exposes working scaffold commands", async () => {
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    await extension.activate();
    assert.equal(extension.isActive, true);
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("wintestkit.showOutput"));
    assert.ok(commands.includes("wintestkit.runDoctor"));
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder);
    await vscode.workspace
      .getConfiguration("wintestkit", folder.uri)
      .update(
        "pythonPath",
        path.resolve(
          __dirname,
          "../../../../../python/.venv/Scripts/python.exe",
        ),
        vscode.ConfigurationTarget.Global,
      );
    await vscode.commands.executeCommand("wintestkit.elements.refresh");
    await vscode.commands.executeCommand("wintestkit.showOutput");
    await vscode.commands.executeCommand("wintestkit.runDoctor");
    const uri = vscode.Uri.joinPath(folder.uri, "screens", "main.py");
    await vscode.window.showTextDocument(uri);
    let lenses: vscode.CodeLens[] = [];
    for (let attempt = 0; attempt < 20; attempt++) {
      lenses =
        (await vscode.commands.executeCommand<vscode.CodeLens[]>(
          "vscode.executeCodeLensProvider",
          uri,
        )) ?? [];
      if (
        lenses.some(
          (lens) => lens.command?.command === "wintestkit.highlightElement",
        )
      )
        break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const highlight = lenses.find(
      (lens) =>
        lens.command?.command === "wintestkit.highlightElement" &&
        lens.command.arguments?.[0]?.qualname === "MainScreen.sign_in",
    );
    assert.ok(highlight, "discovery populates highlight CodeLens");
    try {
      await vscode.commands.executeCommand("wintestkit.launchApp");
      await vscode.commands.executeCommand(
        "wintestkit.highlightElement",
        ...highlight.command!.arguments!,
      );
      const checks = (
        extension.exports as {
          checks: {
            results: Map<string, { status: string; qualname: string }>;
          };
        }
      ).checks;
      assert.ok(
        [...checks.results.values()].some(
          (result) =>
            result.qualname === "MainScreen.sign_in" &&
            result.status === "found",
        ),
      );
      assert.equal(
        vscode.languages
          .getDiagnostics(uri)
          .filter((diagnostic) => diagnostic.source === "WinTestKit").length,
        0,
      );
    } finally {
      await vscode.commands.executeCommand("wintestkit.closeApp");
    }
    await vscode.commands.executeCommand("wintestkit.runTest", {
      id: "tests/test_panels.py::test_panel_a_ok",
    });
    const tests = (
      extension.exports as { tests: { lastResults: Map<string, string> } }
    ).tests;
    assert.equal(
      tests.lastResults.get("tests/test_panels.py::test_panel_a_ok"),
      "passed",
    );
  });
  test("runs login and exposes locator failure messages", async function () {
    this.timeout(120000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder);
    const uri = vscode.Uri.joinPath(folder.uri, "tests", "test_login.py");
    await vscode.window.showTextDocument(uri);
    const lenses = await vscode.commands.executeCommand<vscode.CodeLens[]>(
      "vscode.executeCodeLensProvider",
      uri,
    );
    assert.ok(
      lenses?.some((lens) => lens.command?.command === "wintestkit.runTest"),
    );
    const tests = (
      extension.exports as {
        tests: {
          lastResults: Map<string, string>;
          lastMessages: Map<string, vscode.TestMessage[]>;
        };
      }
    ).tests;
    const login = "tests/test_login.py::test_valid_login";
    await vscode.commands.executeCommand("wintestkit.runTest", { id: login });
    assert.equal(tests.lastResults.get(login), "passed");
    const failure = "tests/test_expected_failure.py::test_misspelled_locator";
    await vscode.commands.executeCommand("wintestkit.runTest", { id: failure });
    assert.equal(tests.lastResults.get(failure), "failed");
    const messages = tests.lastMessages.get(failure);
    assert.ok(
      messages?.some((message) => {
        const text =
          typeof message.message === "string"
            ? message.message
            : message.message.value;
        return text.includes("No element matches");
      }),
    );
    assert.ok(
      messages?.some((message) =>
        message.location?.uri.fsPath.endsWith("test_expected_failure.py"),
      ),
    );
  });
  test("debugs tests and stops at user-code breakpoints", async function () {
    this.timeout(120000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder);
    const testUri = vscode.Uri.joinPath(folder.uri, "tests", "test_panels.py");
    const fixtureUri = vscode.Uri.joinPath(folder.uri, "conftest.py");
    const testLine = readFileSync(testUri.fsPath, "utf8")
      .split("\n")
      .findIndex((line) => line.includes("main.ok_a.click()"));
    const fixtureLine = readFileSync(fixtureUri.fsPath, "utf8")
      .split("\n")
      .findIndex((line) => line.includes("main.menu_file.click()"));
    const breakpoints = [
      new vscode.SourceBreakpoint(
        new vscode.Location(testUri, new vscode.Position(testLine, 0)),
      ),
      new vscode.SourceBreakpoint(
        new vscode.Location(fixtureUri, new vscode.Position(fixtureLine, 0)),
      ),
    ];
    const stoppedFiles = new Set<string>();
    let trackerError: unknown;
    const tracker = vscode.debug.registerDebugAdapterTrackerFactory("debugpy", {
      createDebugAdapterTracker(session) {
        return {
          onDidSendMessage(message: unknown) {
            const event = message as {
              type?: string;
              event?: string;
              body?: { threadId?: number };
            };
            if (
              event.type !== "event" ||
              event.event !== "stopped" ||
              !session.configuration.wintestkitRunId
            )
              return;
            void (async () => {
              const stack = (await session.customRequest("stackTrace", {
                threadId: event.body?.threadId,
              })) as { stackFrames: { source?: { path?: string } }[] };
              for (const frame of stack.stackFrames)
                if (frame.source?.path)
                  stoppedFiles.add(
                    path.resolve(frame.source.path).toLowerCase(),
                  );
              await session.customRequest("continue", {
                threadId: event.body?.threadId,
              });
            })().catch((error) => {
              trackerError = error;
              void vscode.debug.stopDebugging(session);
            });
          },
        };
      },
    });
    vscode.debug.addBreakpoints(breakpoints);
    try {
      await vscode.commands.executeCommand("wintestkit.debugTest", {
        id: "tests/test_panels.py::test_panel_a_ok",
      });
      assert.equal(trackerError, undefined);
      assert.ok(
        stoppedFiles.has(path.resolve(testUri.fsPath).toLowerCase()),
        "test breakpoint is hit",
      );
      assert.ok(
        stoppedFiles.has(path.resolve(fixtureUri.fsPath).toLowerCase()),
        "user fixture breakpoint is hit",
      );
      assert.equal(
        (
          extension.exports as { tests: { lastResults: Map<string, string> } }
        ).tests.lastResults.get("tests/test_panels.py::test_panel_a_ok"),
        "passed",
      );
    } finally {
      vscode.debug.removeBreakpoints(breakpoints);
      tracker.dispose();
    }
  });
});
