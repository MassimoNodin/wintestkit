import { randomBytes } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { rmSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { MAX_PREVIEW_DATA_URL, validatePreviewWebp } from "./objectPreviews";

const prefix = "data:image/webp;base64,";
/** Opened images kept at once; older ones are deleted so nothing accumulates. */
const KEEP = 8;

/**
 * Opens a Spy preview image in VS Code's built-in image viewer (zoom, pan, copy).
 *
 * The viewer needs a file, so the image is written to a private folder in the temp directory.
 * It can show whatever the inspected window showed, so each file is deleted as soon as its editor
 * tab closes, and the whole folder when the extension shuts down.
 */
export class PreviewViewer implements vscode.Disposable {
  private readonly directory = path.join(
    os.tmpdir(),
    "wintestkit-previews-" + randomBytes(6).toString("hex"),
  );
  private readonly files: string[] = [];
  private readonly tabs: vscode.Disposable;
  private serial = 0;

  constructor() {
    this.tabs = vscode.window.tabGroups.onDidChangeTabs((event) => {
      for (const tab of event.closed) {
        const uri = (tab.input as { uri?: vscode.Uri } | undefined)?.uri;
        if (uri) void this.forget(uri.fsPath);
      }
    });
  }

  async show(view: "element" | "window", dataUrl: string): Promise<void> {
    if (
      !dataUrl.startsWith(prefix) ||
      dataUrl.length > MAX_PREVIEW_DATA_URL ||
      !/^[A-Za-z0-9+/]+={0,2}$/.test(dataUrl.slice(prefix.length))
    )
      throw new Error("The preview image is not a valid WebP data URL.");
    const bytes = Buffer.from(dataUrl.slice(prefix.length), "base64");
    validatePreviewWebp(bytes);
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const file = path.join(this.directory, `wintestkit-${view}-${++this.serial}.webp`);
    await writeFile(file, bytes, { flag: "wx", mode: 0o600 });
    this.files.push(file);
    while (this.files.length > KEEP) await this.forget(this.files[0]);
    await vscode.commands.executeCommand("vscode.open", vscode.Uri.file(file), {
      preview: true,
      viewColumn: vscode.ViewColumn.Active,
    });
  }

  private async forget(file: string): Promise<void> {
    const index = this.files.indexOf(file);
    if (index < 0) return;
    this.files.splice(index, 1);
    await rm(file, { force: true });
  }

  dispose(): void {
    this.tabs.dispose();
    this.files.length = 0;
    rmSync(this.directory, { recursive: true, force: true });
  }
}
