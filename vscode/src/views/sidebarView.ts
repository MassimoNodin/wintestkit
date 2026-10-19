import { randomBytes } from "node:crypto";
import * as vscode from "vscode";
import type { TestAppView } from "../settings/testApp";
import type { ElementsTree } from "./elementsTree";
import { sidebarDocument } from "./sidebarDocument";

export const SIDEBAR_VIEW = "wintestkit.sidebar";

/**
 * The WinTestKit sidebar: Test Target above Pages & Flows in one webview. VS Code gives each view
 * of a container a share of the height with no way to ask for a minimum, so a short sidebar
 * squeezed whichever one was last. One page can say how much each part keeps.
 */
export class SidebarView implements vscode.WebviewViewProvider, vscode.Disposable {
  private readonly registration: vscode.Disposable;
  private viewSubscriptions: vscode.Disposable[] = [];
  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly target: TestAppView,
    private readonly pages: ElementsTree,
  ) {
    this.registration = vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW, this, {
      webviewOptions: { retainContextWhenHidden: true },
    });
  }
  resolveWebviewView(view: vscode.WebviewView): void {
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    const media = (...parts: string[]) =>
      vscode.Uri.joinPath(this.extensionUri, "media", ...parts);
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [media("setup"), media("codicons")],
    };
    const href = (uri: vscode.Uri) => view.webview.asWebviewUri(uri).toString();
    view.webview.html = sidebarDocument({
      cspSource: view.webview.cspSource,
      nonce: randomBytes(16).toString("hex"),
      iconsHref: href(media("codicons", "codicon.css")),
      stylesHref: href(media("setup", "setup.css")),
      scriptHref: href(media("setup", "setup.js")),
      ...this.pages.initial(),
    });
    this.target.attach(view);
    this.pages.attach(view);
    this.viewSubscriptions = [
      view.webview.onDidReceiveMessage((value: unknown) => {
        this.target.handleMessage(value);
        this.pages.handleMessage(value);
      }),
    ];
  }
  dispose(): void {
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.registration.dispose();
  }
}
