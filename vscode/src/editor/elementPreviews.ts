import * as vscode from "vscode";
import type { DiscoveryStore, LocatedElement } from "../discovery/store";
import { readObjectPreview, readObjectPreviewStatus } from "../spy/objectPreviews";
import { PreviewViewer } from "../spy/previewViewer";

const openCommand = "wintestkit.openElementCapture";

export interface ElementCapture {
  qualname: string;
  message: string;
  image?: string;
  contextImage?: string;
  width?: number;
  height?: number;
}

function captureAge(capturedAt: string): string {
  const elapsed = Math.max(0, Date.now() - Date.parse(capturedAt));
  if (!Number.isFinite(elapsed)) return "at an unknown time";
  for (const [unit, duration] of [["day", 86400000], ["hour", 3600000], ["minute", 60000]] as const) {
    const count = Math.floor(elapsed / duration);
    if (count >= 1) return count + " " + unit + (count === 1 ? "" : "s") + " ago";
  }
  return "just now";
}

function captureNote(preview: { capturedAt: string; matchCount?: number }, kind: string): string {
  const matches = kind === "elements" && preview.matchCount
    ? " First of " + preview.matchCount + " match" + (preview.matchCount === 1 ? "" : "es") + "."
    : "";
  return "Captured by Check Element " + captureAge(preview.capturedAt) + "." + matches + " Not a live image.";
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
    if (!located || token.isCancellationRequested) return;
    const contents = new vscode.MarkdownString();
    contents.appendText(located.element.qualname);
    contents.appendMarkdown("\n\n");
    try {
      const preview = await readObjectPreview(located.project.root.fsPath, located.element.id);
      if (token.isCancellationRequested || !this.enabled() || !vscode.workspace.isTrusted) return;
      if (!preview) {
        const reason = await readObjectPreviewStatus(located.project.root.fsPath, located.element.id);
        contents.appendText(reason ? "Preview not saved: " + reason : "No saved element capture. Run this element's Check exists CodeLens to capture it.");
      } else {
        const scale = Math.min(1, 320 / preview.width, 200 / preview.height);
        contents.supportHtml = true;
        contents.isTrusted = { enabledCommands: [openCommand] };
        contents.appendMarkdown('<img src="' + preview.cropDataUrl + '" width="' + Math.max(1, Math.round(preview.width * scale)) + '" height="' + Math.max(1, Math.round(preview.height * scale)) + '" alt="Saved element capture" />\n\n');
        contents.appendText(captureNote(preview, located.element.kind));
        contents.appendMarkdown("\n\n");
        const target = { file: located.page.file, qualname: located.element.qualname };
        // A window is its own context: the app-context image would show the same picture.
        const links: (readonly ["element" | "window", string])[] = [["element", "Open full image"]];
        if (located.element.kind !== "window") links.push(["window", "Show app context"]);
        contents.appendMarkdown(links.map(([view, label]) => {
          const argumentsJson = encodeURIComponent(JSON.stringify([{ ...target, view }]));
          return "[" + label + "](command:" + openCommand + "?" + argumentsJson + ")";
        }).join(" \u00b7 "));
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

  async treeCapture(file: string, qualname: string): Promise<ElementCapture | undefined> {
    if (!this.enabled() || !vscode.workspace.isTrusted) return;
    const located = this.discovery.elementByName(vscode.Uri.file(file), qualname);
    if (!located) return;
    let capture: ElementCapture;
    try {
      const preview = await readObjectPreview(located.project.root.fsPath, located.element.id);
      capture = preview ? {
        qualname,
        image: preview.cropDataUrl,
        contextImage: located.element.kind === "window" ? undefined : preview.windowDataUrl,
        width: preview.width,
        height: preview.height,
        message: captureNote(preview, located.element.kind),
      } : { qualname, message: await this.missingMessage(located) };
    } catch (error) {
      this.log.error("Element capture unavailable: " + String(error));
      capture = { qualname, message: "Saved capture unavailable. Run Check exists to capture it again." };
    }
    if (this.enabled() && vscode.workspace.isTrusted) return capture;
  }

  private async missingMessage(located: LocatedElement): Promise<string> {
    const reason = await readObjectPreviewStatus(located.project.root.fsPath, located.element.id);
    return reason ? "Preview not saved: " + reason : "No saved element capture. Run Check exists to capture it.";
  }

  private async open(value: unknown): Promise<void> {
    if (!this.enabled() || !vscode.workspace.isTrusted || !value || typeof value !== "object") return;
    const target = value as Record<string, unknown>;
    if (typeof target.file !== "string" || typeof target.qualname !== "string" ||
      (target.view !== "element" && target.view !== "window")) return;
    const located = this.discovery.elementByName(vscode.Uri.file(target.file), target.qualname);
    if (!located) return;
    try {
      const preview = await readObjectPreview(located.project.root.fsPath, located.element.id);
      if (!preview) {
        await vscode.window.showInformationMessage(await this.missingMessage(located));
        return;
      }
      if (!this.enabled() || !vscode.workspace.isTrusted) return;
      const whole = target.view === "element" || located.element.kind === "window";
      await this.viewer.show(whole ? "element" : "window", whole ? preview.cropDataUrl : preview.windowDataUrl);
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
