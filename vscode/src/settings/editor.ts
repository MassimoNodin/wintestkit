import * as path from "node:path";
import { randomBytes } from "node:crypto";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import { ensureLocalIgnores, readConfiguration, readOptional } from "./files";
import {
  flattenSettings,
  parseSettings,
  settingFields,
  settingSections,
  settingsScope,
  updateSetting,
} from "./model";

export const settingsEditorId = "wintestkit.configuration";

export class ConfigurationEditor implements vscode.CustomTextEditorProvider {
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
      '"></head><body><header><p class="eyebrow">WINTESTKIT</p><h1>Configuration</h1><p id="project"></p><nav aria-label="Configuration file and actions"><button id="local">This machine</button><button id="shared">Shared project</button><button id="source">Open YAML</button><button id="save">Save configuration</button></nav></header><p id="scope"></p><p id="status" role="status" aria-live="polite"></p><main id="fields"></main><script nonce="' +
      nonce +
      '" src="' +
      script +
      '"></script></body></html>';
    let disposed = false;
    let sequence = 0;
    let queue = Promise.resolve();
    const send = async () => {
      const request = ++sequence;
      const version = document.version;
      try {
        const parsed = parseSettings(document.getText(), scope);
        const effective = await readConfiguration(root, {
          [path.basename(document.uri.fsPath)]: document.getText(),
        });
        if (disposed || request !== sequence || version !== document.version)
          return;
        await panel.webview.postMessage({
          type: "state",
          scope,
          name: path.basename(root.fsPath),
          version,
          dirty: document.isDirty,
          fields: settingFields,
          sections: settingSections(scope),
          values: flattenSettings(parsed.toJS({ maxAliasCount: 50 }) ?? {}),
          effective,
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
    const receive = panel.webview.onDidReceiveMessage((message: unknown) => {
      queue = queue
        .then(async () => {
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
          else if (data.type === "save") {
            parseSettings(document.getText(), scope);
            if (scope === "local") await ensureLocalIgnores(root);
            if (!(await document.save()))
              throw new Error("Configuration was not saved.");
            await send();
          } else if (data.type === "browse" && scope === "local") {
            const selection = await vscode.window.showOpenDialog({
              title: "Select application executable",
              filters: { Applications: ["exe"] },
              canSelectMany: false,
            });
            if (selection?.[0]) {
              await apply("app.path", selection[0].fsPath, false);
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
            await apply(data.key, data.value, data.remove);
            await send();
          }
        })
        .catch((error) => {
          void panel.webview.postMessage({
            type: "error",
            message: String(error),
          });
        });
    });
    const changed = vscode.workspace.onDidChangeTextDocument((event) => {
      if (event.document.uri.toString() === document.uri.toString())
        void send();
    });
    const saved = vscode.workspace.onDidSaveTextDocument(() => {
      void send();
    });
    panel.onDidDispose(() => {
      disposed = true;
      sequence++;
      receive.dispose();
      changed.dispose();
      saved.dispose();
    });
  }
}
