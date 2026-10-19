import * as vscode from "vscode";

const KEY = "wintestkit.enabled";
export const ENABLED_CONTEXT = "wintestkit.enabled";

/**
 * Whether the user has turned WinTestKit on for this workspace. Until they do, the extension shows
 * one button and does nothing else: it reads no projects, starts no server and runs no checks.
 */
export class Enablement implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<boolean>();
  readonly onDidChange = this.changed.event;
  constructor(private readonly state: vscode.Memento) {
    void this.publish();
  }
  get enabled(): boolean {
    return this.state.get<boolean>(KEY, false);
  }
  async set(enabled: boolean): Promise<void> {
    if (enabled === this.enabled) return;
    await this.state.update(KEY, enabled);
    await this.publish();
    this.changed.fire(enabled);
  }
  private publish(): Thenable<unknown> {
    return vscode.commands.executeCommand("setContext", ENABLED_CONTEXT, this.enabled);
  }
  dispose(): void {
    this.changed.dispose();
  }
}
