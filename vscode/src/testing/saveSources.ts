import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { Project } from "../server/serverManager";

export async function saveExecutionSources(
  projects: Projects,
  project: Project,
): Promise<boolean> {
  const dirtySources = () => vscode.workspace.textDocuments.filter((document) =>
    document.isDirty &&
    document.languageId === "python" &&
    document.uri.scheme === "file" &&
    projects.projectFor(document.uri)?.root.toString() === project.root.toString(),
  );
  const documents = dirtySources();
  if (!documents.length) return true;
  const choice = await vscode.window.showWarningMessage(
    "WinTestKit executes Python source from disk. Save this project's unsaved Python files before running?",
    { modal: true },
    "Save and Run",
  );
  if (choice !== "Save and Run") return false;
  for (const document of documents) {
    try {
      if (!(await document.save())) return false;
    } catch {
      return false;
    }
  }
  if (dirtySources().length) return false;
  return true;
}
