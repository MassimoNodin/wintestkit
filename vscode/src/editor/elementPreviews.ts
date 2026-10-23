import * as vscode from "vscode";
import type { DiscoveryStore, LocatedElement } from "../discovery/store";
import { readObjectPreview } from "../spy/objectPreviews";
import { PreviewViewer } from "../spy/previewViewer";

const openCommand = "wintestkit.openElementCapture";

function captureAge(capturedAt: string): string {
  const elapsed = Math.max(0, Date.now() - Date.parse(capturedAt));
  if (!Number.isFinite(elapsed)) return "at an unknown time";
  for (const [unit, duration] of [["day", 86400000], ["hour", 3600000], ["minute", 60000]] as const) {
    const count = Math.floor(elapsed / duration);
    if (count >= 1) return count + " " + unit + (count === 1 ? "" : "s") + " ago";
  }
  return "just now";
}

export class ElementPreviews implements vscode.HoverProvider, vscode.Disposable {
  private readonly viewer = new PreviewViewer();
  private readonly subscriptions: vscode.Disposable[];

  constructor(
    private readonly discovery: DiscoveryStore,
    private readonly log: vscode.LogOutputChannel,
    private readonly enabled: () => boolean,
  ) {
    this.subscriptions = [
      vscode.languages.registerHoverProvider({ language: "python", scheme: "file" }, this),
      vscode.commands.registerCommand(openCommand, (target: unknown) => this.open(target)),
    ];
  }

  async provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    token: vscode.CancellationToken,
  ): Promise<vscode.Hover | undefined> {
    if (!this.enabled() || !vscode.workspace.isTrusted || token.isCancellationRequested) return;
    const range = document.getWordRangeAtPosition(position);
    if (!range) return;
    const word = document.getText(range);
    let located = this.discovery.elementNameAt(document.uri, position);
    if (!located || located.element.qualname.split(".").at(-1) !== word) {
      let definitions: (vscode.Location | vscode.LocationLink)[] | undefined;
      try {
        definitions = await vscode.commands.executeCommand<(vscode.Location | vscode.LocationLink)[]>(
          "vscode.executeDefinitionProvider", document.uri, position,
        );
      } catch (error) {
        this.log.error("Element capture definition lookup failed: " + String(error));
        return;
      }
      if (token.isCancellationRequested || !this.enabled() || !vscode.workspace.isTrusted) return;
      const matches = (definitions ?? []).map((definition) => {
        const uri = "targetUri" in definition ? definition.targetUri : definition.uri;
        const targetRange = "targetUri" in definition ? definition.targetSelectionRange ?? definition.targetRange : definition.range;
        return this.discovery.elementNameAt(uri, targetRange.start);
      }).filter((item): item is LocatedElement =>
        !!item && item.element.qualname.split(".").at(-1) === word,
      );
      const identities = new Set(matches.map((item) => item.project.root.toString() + "::" + item.element.id));
      located = identities.size === 1 ? matches[0] : undefined;
    }
    if (!located || located.element.kind !== "element" || token.isCancellationRequested) return;
    const contents = new vscode.MarkdownString();
    contents.appendText(located.element.qualname);
    contents.appendMarkdown("\n\n");
    try {
      const preview = await readObjectPreview(located.project.root.fsPath, located.element.id);
      if (token.isCancellationRequested || !this.enabled() || !vscode.workspace.isTrusted) return;
      if (!preview) {
        contents.appendText("No saved element capture. Run this element's Check exists CodeLens to capture it.");
      } else {
        const scale = Math.min(1, 320 / preview.width, 200 / preview.height);
        contents.supportHtml = true;
        contents.isTrusted = { enabledCommands: [openCommand] };
        contents.appendMarkdown('<img src="' + preview.cropDataUrl + '" width="' + Math.max(1, Math.round(preview.width * scale)) + '" height="' + Math.max(1, Math.round(preview.height * scale)) + '" alt="Saved element capture" />\n\n');
        contents.appendText("Captured by Check Element " + captureAge(preview.capturedAt) + ". Not a live image.");
        contents.appendMarkdown("\n\n");
        const target = { file: located.page.file, qualname: located.element.qualname };
        for (const [view, label] of [["element", "Open full image"], ["window", "Show app context"]] as const) {
          const argumentsJson = encodeURIComponent(JSON.stringify([{ ...target, view }]));
          contents.appendMarkdown("[" + label + "](command:" + openCommand + "?" + argumentsJson + ")" + (view === "element" ? " · " : ""));
        }
        contents.appendMarkdown("\n\n");
        contents.appendText("Run Check exists again to update this capture.");
      }
    } catch (error) {
      this.log.error("Element capture unavailable: " + String(error));
      if (token.isCancellationRequested) return;
      contents.appendText("Saved capture unavailable. Run this element's Check exists CodeLens to capture it again.");
    }
    return new vscode.Hover(contents, range);
  }

  private async open(value: unknown): Promise<void> {
    if (!this.enabled() || !vscode.workspace.isTrusted || !value || typeof value !== "object") return;
    const target = value as Record<string, unknown>;
    if (typeof target.file !== "string" || typeof target.qualname !== "string" ||
      (target.view !== "element" && target.view !== "window")) return;
    const located = this.discovery.elementByName(vscode.Uri.file(target.file), target.qualname);
    if (!located || located.element.kind !== "element") return;
    try {
      const preview = await readObjectPreview(located.project.root.fsPath, located.element.id);
      if (!preview || !this.enabled() || !vscode.workspace.isTrusted) return;
      await this.viewer.show(target.view, target.view === "element" ? preview.cropDataUrl : preview.windowDataUrl);
    } catch (error) {
      this.log.error("Element capture unavailable: " + String(error));
      await vscode.window.showErrorMessage("The saved element capture could not be opened. Run Check exists to capture it again.");
    }
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose();
    this.viewer.dispose();
  }
}
