import * as vscode from "vscode";
import type { Project, ServerManager } from "../server/serverManager";
import { readConfiguration } from "../settings/files";

/** Ask for a safe, mode-aware recovery and return true only when retry is appropriate. */
export async function recoverStoppedApp(
  project: Project,
  servers: ServerManager,
): Promise<boolean> {
  const config = await readConfiguration(project.root);
  if (config.launch === "attach") {
    const name = String(config["app.process"] ?? "the app").replace(/\.exe$/i, "");
    const choice = await vscode.window.showInformationMessage(
      `Attach mode won't start or close ${name}. Start it yourself, then choose Refresh to retry.`,
      "Refresh",
    );
    if (choice !== "Refresh") return false;
    const connection = await servers.get(project);
    const status = await connection.client.request<{ running: boolean }>(
      "app.status",
    );
    if (!status.running) {
      void vscode.window.showInformationMessage(`${name} is still stopped.`);
      return false;
    }
    return true;
  }

  const choice = await vscode.window.showInformationMessage(
    "The app isn't running.",
    "Launch App",
  );
  if (choice !== "Launch App") return false;
  await vscode.commands.executeCommand("wintestkit.launchAppStrict", {
    resourceUri: project.root,
  });
  return true;
}
