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
    const uri = vscode.Uri.joinPath(folder.uri, "pages", "main.py");
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
        lens.command.arguments?.[0]?.qualname === "MainPage.sign_in",
    );
    assert.ok(highlight, "discovery populates highlight CodeLens");
    type TreeNode = {
      label: string;
      children: TreeNode[];
      file?: string;
      qualname?: string;
    };
    const elements = (
      extension.exports as {
        elements: {
          getChildren(): TreeNode[];
          getTreeItem(node: TreeNode): vscode.TreeItem;
        };
      }
    ).elements;
    const mainPage = elements
      .getChildren()
      .find((node) => node.label === "MainPage");
    assert.ok(mainPage);
    const credentials = mainPage.children.find(
      (node) => node.label === "credentials",
    );
    const signIn = credentials?.children.find(
      (node) => node.label === "sign_in",
    );
    assert.ok(signIn, "tree nests sign_in under credentials");
    assert.equal(elements.getTreeItem(signIn).contextValue, "element");
    await vscode.commands.executeCommand("wintestkit.elements.goTo", signIn);
    assert.equal(
      vscode.window.activeTextEditor?.document.uri.fsPath
        .toLowerCase()
        .replaceAll("\\", "/"),
      signIn.file?.toLowerCase().replaceAll("\\", "/"),
    );
    try {
      await vscode.commands.executeCommand("wintestkit.launchApp");
      await vscode.commands.executeCommand(
        "wintestkit.highlightElement",
        signIn,
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
            result.qualname === "MainPage.sign_in" && result.status === "found",
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
  test("inspects live controls through the Spy bridge", async function () {
    this.timeout(120000);
    const extension = vscode.extensions.getExtension("wintestkit.wintestkit");
    assert.ok(extension);
    const spy = (
      extension.exports as {
        spy: {
          resolveWebviewView(view: vscode.WebviewView): Promise<void>;
          refresh(): Promise<void>;
        };
      }
    ).spy;
    type Node = {
      nodeId: string;
      hasChildren: boolean;
      info: { name: string; controlType: string };
    };
    type Message = {
      type: string;
      nodeId?: string;
      nodes?: Node[];
      suggestion?: { code: string; unique: boolean };
      picking?: boolean;
    };
    const messages: Message[] = [];
    let receive: (value: unknown) => void = () => {};
    let disposeView: () => void = () => {};
    const disposable = () => ({ dispose() {} });
    const webview = {
      options: {},
      html: "",
      cspSource: "vscode-resource:",
      asWebviewUri: (uri: vscode.Uri) => uri,
      postMessage: (message: Message) => {
        messages.push(message);
        return Promise.resolve(true);
      },
      onDidReceiveMessage: (callback: (value: unknown) => void) => {
        receive = callback;
        return disposable();
      },
    };
    const view = {
      webview,
      visible: true,
      onDidChangeVisibility: disposable,
      onDidDispose: (callback: () => void) => {
        disposeView = callback;
        return disposable();
      },
    };
    const wait = async (predicate: () => boolean) => {
      for (let attempt = 0; attempt < 100; attempt++) {
        if (predicate()) return;
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      assert.fail(
        "Spy message did not arrive: " + JSON.stringify(messages.slice(-3)),
      );
    };
    try {
      await vscode.commands.executeCommand("wintestkit.launchApp");
      await spy.resolveWebviewView(view as unknown as vscode.WebviewView);
      await spy.refresh();
      assert.ok(webview.html.includes("default-src 'none'"));
      const pending = [
        ...(messages.find((message) => message.type === "roots")?.nodes ?? []),
      ];
      let signIn: Node | undefined;
      for (let visited = 0; pending.length && visited < 150; visited++) {
        const node = pending.shift()!;
        if (
          node.info.controlType === "Button" &&
          node.info.name === "Sign in"
        ) {
          signIn = node;
          break;
        }
        if (!node.hasChildren) continue;
        receive({ type: "expand", nodeId: node.nodeId });
        await wait(() =>
          messages.some(
            (message) =>
              message.type === "children" && message.nodeId === node.nodeId,
          ),
        );
        pending.push(
          ...messages.find(
            (message) =>
              message.type === "children" && message.nodeId === node.nodeId,
          )!.nodes!,
        );
      }
      assert.ok(signIn, "Spy finds the demo Sign in button");
      receive({ type: "select", nodeId: signIn.nodeId });
      await wait(() =>
        messages.some(
          (message) =>
            message.type === "selected" && message.nodeId === signIn!.nodeId,
        ),
      );
      const selected = messages.find(
        (message) =>
          message.type === "selected" && message.nodeId === signIn!.nodeId,
      )!;
      assert.ok(selected.suggestion?.code.includes('name="Sign in"'));
      assert.equal(selected.suggestion?.unique, true);
      const folder = vscode.workspace.workspaceFolders?.[0];
      assert.ok(folder);
      const scratch = vscode.Uri.joinPath(
        folder.uri,
        "pages",
        "_wtk_spy_e2e.py",
      );
      assert.equal(
        await vscode.workspace.fs.stat(scratch).then(
          () => true,
          () => false,
        ),
        false,
        "scratch page must not already exist",
      );
      const compute = (
        extension.exports as {
          computeInsertion(
            source: string,
            page: null,
            newPage: { className: string },
            suggestion: unknown,
            attributeName: string,
          ): {
            edits: {
              range: {
                start: { line: number; character: number };
                end: { line: number; character: number };
              };
              text: string;
            }[];
          };
        }
      ).computeInsertion;
      const insertion = compute(
        "",
        null,
        { className: "SpyIntegrationPage" },
        selected.suggestion,
        "sign_in",
      );
      try {
        const edit = new vscode.WorkspaceEdit();
        edit.createFile(scratch, { overwrite: false });
        for (const change of insertion.edits)
          edit.replace(
            scratch,
            new vscode.Range(
              change.range.start.line,
              change.range.start.character,
              change.range.end.line,
              change.range.end.character,
            ),
            change.text,
          );
        assert.equal(await vscode.workspace.applyEdit(edit), true);
        const document = await vscode.workspace.openTextDocument(scratch);
        await vscode.window.showTextDocument(document);
        assert.equal(await document.save(), true);
        let insertedLens: vscode.CodeLens | undefined;
        for (let attempt = 0; attempt < 40; attempt++) {
          const lenses = await vscode.commands.executeCommand<
            vscode.CodeLens[]
          >("vscode.executeCodeLensProvider", scratch);
          insertedLens = lenses?.find(
            (lens) =>
              lens.command?.command === "wintestkit.highlightElement" &&
              lens.command.arguments?.[0]?.qualname ===
                "SpyIntegrationPage.sign_in",
          );
          if (insertedLens) break;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        assert.ok(
          insertedLens,
          "inserted Spy locator becomes a discovered element",
        );
        await vscode.commands.executeCommand(
          "wintestkit.highlightElement",
          ...insertedLens.command!.arguments!,
        );
        const checks = (
          extension.exports as {
            checks: {
              results: Map<string, { qualname: string; status: string }>;
            };
          }
        ).checks;
        assert.ok(
          [...checks.results.values()].some(
            (result) =>
              result.qualname === "SpyIntegrationPage.sign_in" &&
              result.status === "found",
          ),
        );
      } finally {
        if (
          vscode.window.activeTextEditor?.document.uri.toString() ===
          scratch.toString()
        )
          await vscode.commands.executeCommand(
            "workbench.action.closeActiveEditor",
          );
        if (
          await vscode.workspace.fs.stat(scratch).then(
            () => true,
            () => false,
          )
        )
          await vscode.workspace.fs.delete(scratch);
      }
      receive({ type: "pick" });
      await wait(() =>
        messages.some(
          (message) => message.type === "state" && message.picking === true,
        ),
      );
      receive({ type: "stopPick" });
      await wait(
        () =>
          messages.at(-1)?.type === "state" &&
          messages.at(-1)?.picking === false,
      );
    } finally {
      disposeView();
      await vscode.commands.executeCommand("wintestkit.closeApp");
    }
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
