import * as vscode from "vscode";
import { parse as parseToml } from "smol-toml";
import {
  flattenSettings,
  parseSettings,
  settingFields,
  updateSetting,
} from "./model";

export const configurationNames = [
  "pyproject.toml",
  "wintestkit.yaml",
  "wintestkit.local.toml",
  "wintestkit.local.yaml",
];
export const localIgnorePatterns = [
  "wintestkit.local.toml",
  "wintestkit.local.yaml",
  ".venv/",
  "__pycache__/",
  ".pytest_cache/",
  ".ruff_cache/",
  "wtk-report/",
  "wtk-results/",
];

export async function readOptional(
  uri: vscode.Uri,
): Promise<string | undefined> {
  try {
    return Buffer.from(await vscode.workspace.fs.readFile(uri)).toString(
      "utf8",
    );
  } catch (error) {
    if (
      error instanceof vscode.FileSystemError &&
      error.code === "FileNotFound"
    )
      return undefined;
    throw error;
  }
}

export async function ensureLocalIgnores(root: vscode.Uri): Promise<void> {
  const uri = vscode.Uri.joinPath(root, ".gitignore");
  const original = (await readOptional(uri)) ?? "";
  const existing = new Set(original.split(/\r?\n/));
  const missing = localIgnorePatterns.filter(
    (pattern) => !existing.has(pattern),
  );
  if (!missing.length) return;
  let document: vscode.TextDocument;
  try {
    document = await vscode.workspace.openTextDocument(uri);
  } catch (error) {
    if ((await readOptional(uri)) !== undefined) throw error;
    await vscode.workspace.fs.writeFile(uri, Buffer.from(""));
    document = await vscode.workspace.openTextDocument(uri);
  }
  if (document.isDirty)
    throw new Error("Save .gitignore before creating local configuration.");
  const edit = new vscode.WorkspaceEdit();
  edit.insert(
    uri,
    document.positionAt(document.getText().length),
    (original && !original.endsWith("\n") ? "\n" : "") +
      missing.join("\n") +
      "\n",
  );
  if (!(await vscode.workspace.applyEdit(edit)) || !(await document.save()))
    throw new Error("Cannot update .gitignore.");
}

export async function readConfiguration(
  root: vscode.Uri,
  overrides: Record<string, string> = {},
  includeDefaults = true,
): Promise<Record<string, unknown>> {
  const merged: Record<string, unknown> = includeDefaults
    ? Object.fromEntries(
        settingFields
          .filter((field) => field.default !== undefined)
          .map((field) => [field.key, field.default]),
      )
    : {};
  for (const name of configurationNames) {
    const source =
      overrides[name] ?? (await readOptional(vscode.Uri.joinPath(root, name)));
    if (source === undefined) continue;
    if (name.endsWith(".yaml")) {
      const document = parseSettings(
        source,
        name.includes(".local.") ? "local" : "shared",
      );
      Object.assign(
        merged,
        flattenSettings(document.toJS({ maxAliasCount: 50 }) ?? {}),
      );
    } else {
      const parsed = parseToml(source) as {
        tool?: { wintestkit?: Record<string, unknown> };
      };
      Object.assign(merged, flattenSettings(parsed.tool?.wintestkit ?? {}));
    }
  }
  return merged;
}

/**
 * Writes settings to the project's local, Git-ignored configuration (`wintestkit.local.yaml`),
 * creating it when needed. A value of `undefined` removes the setting.
 */
export async function writeLocalSettings(
  root: vscode.Uri,
  changes: Record<string, unknown>,
): Promise<void> {
  await ensureLocalIgnores(root);
  const uri = vscode.Uri.joinPath(root, "wintestkit.local.yaml");
  let source =
    (await readOptional(uri)) ??
    "# Local machine overrides. This file is ignored by Git.\n{}\n";
  for (const [key, value] of Object.entries(changes))
    source = updateSetting(source, "local", key, value, value === undefined);
  await vscode.workspace.fs.writeFile(uri, Buffer.from(source, "utf8"));
}
