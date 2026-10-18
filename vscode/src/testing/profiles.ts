import type * as vscode from "vscode";

export function disposeRunProfiles(...profiles: vscode.TestRunProfile[]): void {
  profiles.forEach((profile) => profile.dispose());
}
