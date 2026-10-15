import * as vscode from "vscode";
import * as path from "node:path";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { PageEntry, Suggestion } from "../protocol/generated";
import type { Project } from "../server/serverManager";
import { computeInsertion, validIdentifier } from "./insertionModel";

export function registerInsertElement(
  projects: Projects,
  discovery: DiscoveryStore,
  log: vscode.LogOutputChannel,
): vscode.Disposable {
  return vscode.commands.registerCommand(
    "wintestkit.spy.addToPage",
    async (suggestion: Suggestion) => {
      try {
        if (!vscode.workspace.isTrusted)
          throw new Error("Trust the workspace before adding page elements.");
        if (!suggestion || typeof suggestion.code !== "string") return;
        const choices: (vscode.QuickPickItem & {
          project?: Project;
          page?: PageEntry;
        })[] = projects.all.flatMap((project) =>
          (discovery.get(project)?.pages ?? []).map((page) => ({
            label: page.name,
            description: path.relative(project.root.fsPath, page.file),
            detail: project.name,
            project,
            page,
          })),
        );
        choices.push({ label: "$(add) New page…" });
        const choice = await vscode.window.showQuickPick(choices, {
          placeHolder: "Add the picked element to a page",
        });
        if (!choice) return;
        let project = choice.project;
        let uri: vscode.Uri;
        let newPage: { className: string; window?: string } | undefined;
        if (choice.page) uri = vscode.Uri.file(choice.page.file);
        else {
          project =
            projects.all.length === 1
              ? projects.all[0]
              : (
                  await vscode.window.showQuickPick(
                    projects.all.map((candidate) => ({
                      label: candidate.name,
                      description: candidate.root.fsPath,
                      project: candidate,
                    })),
                    { placeHolder: "Choose a project" },
                  )
                )?.project;
          if (!project) return;
          const className = await vscode.window.showInputBox({
            prompt: "Page class name",
            value: "MainPage",
            validateInput: (value) =>
              /^[A-Z][A-Za-z0-9]*$/.test(value)
                ? undefined
                : "Use a PascalCase class name.",
          });
          if (!className) return;
          const files = await vscode.workspace.findFiles(
            new vscode.RelativePattern(project.root, "pages/*.py"),
          );
          const file = await vscode.window.showQuickPick(
            [
              ...files.map((uri) => ({
                label: path.basename(uri.fsPath),
                uri,
              })),
              { label: "$(add) New file…", uri: undefined },
            ],
            { placeHolder: "Choose a page file" },
          );
          if (!file) return;
          if (file.uri) uri = file.uri;
          else {
            const filename = await vscode.window.showInputBox({
              prompt: "New page filename",
              value: "main.py",
              validateInput: (value) =>
                /^[A-Za-z_][A-Za-z0-9_]*\.py$/.test(value)
                  ? undefined
                  : "Use a Python filename such as main.py.",
            });
            if (!filename) return;
            uri = vscode.Uri.joinPath(project.root, "pages", filename);
          }
          if (
            (discovery.get(project)?.pages ?? []).some(
              (page) =>
                page.file.replaceAll("\\", "/").toLowerCase() ===
                  uri.fsPath.replaceAll("\\", "/").toLowerCase() &&
                page.name === className,
            )
          )
            throw new Error("That page class already exists in this file.");
          newPage = { className, window: suggestion.window?.code };
        }
        const attributeName = await vscode.window.showInputBox({
          prompt: "Element attribute name",
          value: suggestion.attributeName,
          validateInput: (value) =>
            !validIdentifier(value)
              ? "Use a Python identifier that is not a keyword."
              : choice.page?.elements.some((element) => element.name === value)
                ? "That attribute is already defined."
                : undefined,
        });
        if (!attributeName || !project) return;
        const exists = await vscode.workspace.fs.stat(uri).then(
          () => true,
          () => false,
        );
        const document = exists
          ? await vscode.workspace.openTextDocument(uri)
          : undefined;
        const source = document?.getText() ?? "";
        const page = choice.page
          ? (discovery.pageById(choice.page.id, project) ?? choice.page)
          : null;
        const insertion = computeInsertion(
          source,
          page,
          newPage,
          suggestion,
          attributeName,
        );
        const edit = new vscode.WorkspaceEdit();
        if (!document) {
          await vscode.workspace.fs.createDirectory(
            vscode.Uri.joinPath(project.root, "pages"),
          );
          edit.createFile(uri, { overwrite: false });
        }
        for (const change of insertion.edits)
          edit.replace(
            uri,
            new vscode.Range(
              change.range.start.line,
              change.range.start.character,
              change.range.end.line,
              change.range.end.character,
            ),
            change.text,
          );
        if (!(await vscode.workspace.applyEdit(edit)))
          throw new Error("Could not insert the element.");
        const updated = await vscode.workspace.openTextDocument(uri);
        const lines = updated.getText().split(/\r?\n/);
        const classLine = lines.findIndex((text) =>
          new RegExp(
            "^\\s*class\\s+" + (page?.name ?? newPage!.className) + "\\b",
          ).test(text),
        );
        const relativeLine = lines
          .slice(classLine + 1)
          .findIndex((text) =>
            new RegExp("^\\s*" + attributeName + "\\s*=").test(text),
          );
        const line = classLine + 1 + relativeLine;
        const editor = await vscode.window.showTextDocument(updated, {
          selection: new vscode.Range(
            Math.max(0, line),
            0,
            Math.max(0, line),
            0,
          ),
        });
        editor.revealRange(
          editor.selection,
          vscode.TextEditorRevealType.InCenterIfOutsideViewport,
        );
        discovery.refresh(project);
      } catch (error) {
        log.error(String(error));
        await vscode.window.showErrorMessage(
          error instanceof Error ? error.message : String(error),
        );
      }
    },
  );
}
