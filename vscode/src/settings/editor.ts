import * as path from "node:path";
import { randomBytes } from "node:crypto";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import { ensureLocalIgnores, readConfiguration, readOptional } from "./files";
import {
  flattenSettings,
  parseSettings,
  repositoryPath,
  settingFields,
  settingSections,
  settingsScope,
  updateSetting,
  type SettingsScope,
} from "./model";

export const settingsEditorId = "wintestkit.configuration";

export class ConfigurationEditor implements vscode.CustomTextEditorProvider {
  // The pages that are open. User and Repository Settings read each other's file, so only one of
  // them is kept open per project: a page that is left open would show a stale copy of the other.
  private readonly pages = new Set<{
    folder: string;
    scope: SettingsScope;
    panel: vscode.WebviewPanel;
  }>();

  constructor(
    private readonly projects: Projects,
    private readonly extensionUri: vscode.Uri,
  ) {}

  async open(root?: vscode.Uri, local = true): Promise<void> {
    if (!vscode.workspace.isTrusted)
      throw new Error(
        "Trust the workspace before editing WinTestKit configuration.",
      );
    if (
      root &&
      /wintestkit(?:\.local)?\.yaml$/.test(path.basename(root.fsPath))
    )
      root = vscode.Uri.file(path.dirname(root.fsPath));
    if (!root) {
      const active = vscode.window.activeTextEditor?.document.uri;
      const project = active ? this.projects.projectFor(active) : undefined;
      const choices = this.projects.all;
      root = project?.root;
      if (!root && choices.length === 1) root = choices[0].root;
      if (!root && choices.length > 1)
        root = (
          await vscode.window.showQuickPick(
            choices.map((project) => ({
              label: project.name,
              description: project.root.fsPath,
              root: project.root,
            })),
            { placeHolder: "Choose a WinTestKit project" },
          )
        )?.root;
    }
    if (!root) return;
    await ensureLocalIgnores(root);
    const uri = vscode.Uri.joinPath(
      root,
      local ? "wintestkit.local.yaml" : "wintestkit.yaml",
    );
    if ((await readOptional(uri)) === undefined)
      await vscode.workspace.fs.writeFile(
        uri,
        Buffer.from(
          local
            ? "# Local machine overrides. This file is ignored by Git.\n{}\n"
            : "# Shared project configuration. Put machine paths in wintestkit.local.yaml.\n{}\n",
        ),
      );
    await vscode.commands.executeCommand(
      "vscode.openWith",
      uri,
      settingsEditorId,
    );
  }

  async resolveCustomTextEditor(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel,
  ): Promise<void> {
    const root = vscode.Uri.file(path.dirname(document.uri.fsPath));
    const scope = settingsScope(document.uri.fsPath);
    const page = { folder: root.fsPath.toLowerCase(), scope, panel };
    for (const other of [...this.pages])
      if (other.folder === page.folder && other.scope !== scope)
        other.panel.dispose();
    this.pages.add(page);
    panel.onDidDispose(() => this.pages.delete(page));
    const nonce = randomBytes(16).toString("hex");
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, "media", "settings"),
      ],
    };
    const script = panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "settings", "editor.js"),
    );
    const style = panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "settings", "editor.css"),
    );
    panel.webview.html =
      '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src ' +
      panel.webview.cspSource +
      "; script-src 'nonce-" +
      nonce +
      '\';"><link rel="stylesheet" href="' +
      style +
      '"></head><body><header><p class="eyebrow">WINTESTKIT</p><h1>Configuration</h1><p id="project"></p></header><nav aria-label="Configuration file and actions"><div class="segmented" role="group" aria-label="Configuration file"><button id="local">User Settings</button><button id="shared">Repository Settings</button></div><button id="source">Open YAML</button></nav><div class="scope-row"><p id="scope"></p><span id="saving" role="status" hidden><span class="spinner" aria-hidden="true"></span>Saving</span></div><p id="status" role="status" aria-live="polite"></p><main id="fields"></main><script nonce="' +
      nonce +
      '" src="' +
      script +
      '"></script></body></html>';
    let disposed = false;
    let sequence = 0;
    let queue = Promise.resolve();
    // Set from an undo or redo until its save has been made, which the form shows as "Saving".
    let historyPending: ReturnType<typeof setTimeout> | undefined;
    // The settings of one YAML file in this folder. The file being edited is read from its buffer,
    // the other from disk; a file that is missing or invalid has no settings to show.
    const settingsOf = async (file: string): Promise<Record<string, unknown>> => {
      try {
        const text =
          file === path.basename(document.uri.fsPath)
            ? document.getText()
            : await readOptional(vscode.Uri.joinPath(root, file));
        if (text === undefined) return {};
        return flattenSettings(
          parseSettings(text).toJS({ maxAliasCount: 50 }) ?? {},
        );
      } catch {
        return {};
      }
    };
    const send = async () => {
      const request = ++sequence;
      const version = document.version;
      try {
        const parsed = parseSettings(document.getText());
        const name = path.basename(document.uri.fsPath);
        const repository = await settingsOf("wintestkit.yaml");
        const user = await settingsOf("wintestkit.local.yaml");
        const effective = await readConfiguration(root, {
          [name]: document.getText(),
        });
        // What every setting would be without this file: the baseline a change is measured from.
        const inherited = await readConfiguration(root, { [name]: "{}\n" });
        if (disposed || request !== sequence || version !== document.version)
          return;
        await panel.webview.postMessage({
          type: "state",
          scope,
          name: path.basename(root.fsPath),
          version,
          dirty: document.isDirty,
          saving: historyPending !== undefined,
          fields: settingFields,
          sections: settingSections(scope),
          values: flattenSettings(parsed.toJS({ maxAliasCount: 50 }) ?? {}),
          effective,
          inherited,
          repository,
          user,
        });
      } catch (error) {
        if (!disposed && request === sequence)
          await panel.webview.postMessage({
            type: "error",
            message: String(error) + " Open YAML to correct the file.",
          });
      }
    };
    const apply = async (key: string, value: unknown, remove: boolean) => {
      const text = updateSetting(document.getText(), scope, key, value, remove);
      const edit = new vscode.WorkspaceEdit();
      edit.replace(
        document.uri,
        new vscode.Range(
          document.positionAt(0),
          document.positionAt(document.getText().length),
        ),
        text,
      );
      if (!(await vscode.workspace.applyEdit(edit)))
        throw new Error("Configuration changed. Try again.");
    };
    const save = async () => {
      parseSettings(document.getText());
      if (scope === "local") await ensureLocalIgnores(root);
      if (!(await document.save()))
        throw new Error("Configuration was not saved.");
    };
    // Both files are saved as they change.
    const commit = async (key: string, value: unknown, remove: boolean) => {
      await apply(key, value, remove);
      await save();
    };
    // The setting a change is for, so an error can say which text box it belongs to.
    let pendingKey: string | undefined;
    const receive = panel.webview.onDidReceiveMessage((message: unknown) => {
      queue = queue
        .then(async () => {
          pendingKey = undefined;
          if (!message || typeof message !== "object") return;
          const data = message as Record<string, unknown>;
          if (data.type === "ready") {
            await send();
            return;
          }
          if (!vscode.workspace.isTrusted)
            throw new Error("Trust the workspace before editing settings.");
          if (
            data.type === "scope" &&
            (data.scope === "local" || data.scope === "shared")
          )
            await this.open(root, data.scope === "local");
          else if (data.type === "source")
            await vscode.commands.executeCommand(
              "vscode.openWith",
              document.uri,
              "default",
            );
          else if (data.type === "browse") {
            const selection = await vscode.window.showOpenDialog({
              title: "Select application executable",
              filters: { Applications: ["exe"] },
              canSelectMany: false,
              defaultUri: root,
            });
            if (selection?.[0]) {
              pendingKey = "app.path";
              await commit(
                "app.path",
                scope === "local"
                  ? selection[0].fsPath
                  : repositoryPath(root.fsPath, selection[0].fsPath),
                false,
              );
              await panel.webview.postMessage({
                type: "committed",
                key: "app.path",
              });
              await send();
            }
          } else if (
            data.type === "change" &&
            typeof data.key === "string" &&
            typeof data.remove === "boolean"
          ) {
            if (data.version !== document.version) {
              await send();
              throw new Error(
                "Settings changed. Review the refreshed form and try again.",
              );
            }
            pendingKey = data.key;
            await commit(data.key, data.value, data.remove);
            await panel.webview.postMessage({
              type: "committed",
              key: data.key,
            });
            await send();
          }
        })
        .catch((error) => {
          void panel.webview.postMessage({
            type: "error",
            message: String(error),
            key: pendingKey,
          });
        });
    });
    // Undo and redo rewrite the buffer without going through commit, which would leave the file
    // unsaved; save them as well so the form and the file never disagree. A buffer that no longer
    // parses stays unsaved and the form reports the error.
    // VS Code can still report the document as clean in the change event for the first edit after a
    // save, and announces the dirty state in a following event, so the step stays pending until
    // the document is dirty (or a moment has passed, when the undo returned it to the saved state).
    // The form shows "Saving" for as long as a step is pending.
    const saveHistoryStep = () => {
      queue = queue.then(async () => {
        if (disposed || historyPending === undefined || !document.isDirty) {
          await send();
          return;
        }
        clearTimeout(historyPending);
        historyPending = undefined;
        let failure: unknown;
        try {
          if (vscode.workspace.isTrusted) await save();
        } catch (error) {
          failure = error;
        }
        await send();
        // After the refresh: the state message would otherwise replace the error.
        if (failure !== undefined)
          void panel.webview.postMessage({
            type: "error",
            message: String(failure),
          });
      });
    };
    const changed = vscode.workspace.onDidChangeTextDocument((event) => {
      if (event.document.uri.toString() !== document.uri.toString()) return;
      if (
        event.reason === vscode.TextDocumentChangeReason.Undo ||
        event.reason === vscode.TextDocumentChangeReason.Redo
      ) {
        if (historyPending !== undefined) clearTimeout(historyPending);
        historyPending = setTimeout(() => {
          historyPending = undefined;
          void send();
        }, 500);
      }
      if (historyPending !== undefined) saveHistoryStep();
      else void send();
    });
    const saved = vscode.workspace.onDidSaveTextDocument(() => {
      void send();
    });
    panel.onDidDispose(() => {
      disposed = true;
      sequence++;
      if (historyPending !== undefined) clearTimeout(historyPending);
      receive.dispose();
      changed.dispose();
      saved.dispose();
    });
  }
}
