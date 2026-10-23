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

vi.mock("../../src/settings/files", () => ({
  ensureLocalIgnores: async () => undefined,
  readConfiguration: async () => ({}),
  readOptional: async () => undefined,
}));

import { ConfigurationEditor } from "../../src/settings/editor";

function panel() {
  const disposers: (() => void)[] = [];
  const messages: Record<string, unknown>[] = [];
  const received: { listener?: (message: unknown) => void } = {};
  const fake = {
    disposed: false,
    messages,
    received,
    webview: {
      options: {},
      cspSource: "csp",
      html: "",
      asWebviewUri: (uri: unknown) => uri,
      onDidReceiveMessage: (listener: (message: unknown) => void) => {
        received.listener = listener;
        return { dispose() {} };
      },
      postMessage: async (message: Record<string, unknown>) => {
        messages.push(message);
        return true;
      },
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

  it("asks the page it opens to scroll to a setting, once", async () => {
    const provider = editor();
    // What open() records when User Settings send you to a repository setting.
    (provider as unknown as { pendingFocus: unknown }).pendingFocus = {
      file: "c:/work/app/wintestkit.yaml",
      key: "object_previews_share",
    };
    const repository = panel();
    await open(provider, "C:/work/app/wintestkit.yaml", repository);
    const states = async () => {
      repository.received.listener?.({ type: "ready" });
      await new Promise((resolve) => setTimeout(resolve, 0));
      return repository.messages.filter((message) => message.type === "state");
    };
    expect((await states())[0]).toMatchObject({ focus: "object_previews_share" });
    expect((await states())[1]?.focus).toBeUndefined();
  });

  it("does not send another file's pending focus to a page", async () => {
    const provider = editor();
    (provider as unknown as { pendingFocus: unknown }).pendingFocus = {
      file: "c:/work/app/wintestkit.yaml",
      key: "object_previews_share",
    };
    const user = panel();
    await open(provider, "C:/work/app/wintestkit.local.yaml", user);
    user.received.listener?.({ type: "ready" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(user.messages.find((message) => message.type === "state")?.focus).toBeUndefined();
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
