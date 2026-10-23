import { describe, expect, it, vi } from "vitest";

vi.mock("vscode", () => {
  const uri = (fsPath: string) => ({ fsPath, toString: () => fsPath });
  return {
    Uri: {
      file: uri,
      joinPath: (base: { fsPath: string }, ...parts: string[]) =>
        uri([base.fsPath, ...parts].join("/")),
    },
    workspace: {
      isTrusted: true,
      onDidChangeTextDocument: () => ({ dispose() {} }),
      onDidSaveTextDocument: () => ({ dispose() {} }),
    },
    window: {},
    commands: {},
  };
});

import { ConfigurationEditor } from "../../src/settings/editor";

function panel() {
  const disposers: (() => void)[] = [];
  const fake = {
    disposed: false,
    webview: {
      options: {},
      cspSource: "csp",
      html: "",
      asWebviewUri: (uri: unknown) => uri,
      onDidReceiveMessage: () => ({ dispose() {} }),
      postMessage: async () => true,
    },
    onDidDispose: (listener: () => void) => {
      disposers.push(listener);
      return { dispose() {} };
    },
    dispose() {
      if (fake.disposed) return;
      fake.disposed = true;
      for (const listener of disposers) listener();
    },
  };
  return fake;
}

function document(fsPath: string) {
  return {
    uri: { fsPath, toString: () => fsPath },
    version: 1,
    isDirty: false,
    getText: () => "{}\n",
  };
}

describe("configuration pages", () => {
  const editor = () =>
    new ConfigurationEditor({} as never, { fsPath: "ext" } as never);
  const open = (
    provider: ConfigurationEditor,
    file: string,
    target: ReturnType<typeof panel>,
  ) =>
    provider.resolveCustomTextEditor(document(file) as never, target as never);

  it("closes the other page when User or Repository Settings opens", async () => {
    const provider = editor();
    const user = panel();
    const repository = panel();
    await open(provider, "C:/work/app/wintestkit.local.yaml", user);
    expect(user.disposed).toBe(false);
    await open(provider, "C:/work/app/wintestkit.yaml", repository);
    expect(user.disposed).toBe(true);
    expect(repository.disposed).toBe(false);
    const again = panel();
    await open(provider, "C:/work/app/wintestkit.local.yaml", again);
    expect(repository.disposed).toBe(true);
    expect(again.disposed).toBe(false);
  });

  it("leaves the pages of another project alone", async () => {
    const provider = editor();
    const first = panel();
    const second = panel();
    await open(provider, "C:/work/one/wintestkit.local.yaml", first);
    await open(provider, "C:/work/two/wintestkit.yaml", second);
    expect(first.disposed).toBe(false);
    expect(second.disposed).toBe(false);
  });

  it("forgets a page that was closed", async () => {
    const provider = editor();
    const user = panel();
    await open(provider, "C:/work/app/wintestkit.local.yaml", user);
    user.dispose();
    const repository = panel();
    await open(provider, "C:/work/app/wintestkit.yaml", repository);
    expect(repository.disposed).toBe(false);
  });
});
