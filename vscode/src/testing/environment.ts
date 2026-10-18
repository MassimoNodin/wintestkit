import type { Project } from "../server/serverManager";

export async function offerDoctorForRun(
  exitCode: number | null,
  project: Project,
  showWarning: (message: string, action: string) => PromiseLike<string | undefined>,
  executeCommand: (command: string, target: { resourceUri: Project["root"] }) => PromiseLike<unknown>,
): Promise<void> {
  if (exitCode !== 3) return;
  const choice = await showWarning(
    "WinTestKit's environment checks blocked this run.",
    "Check Environment",
  );
  if (choice === "Check Environment")
    await executeCommand("wintestkit.runDoctor", { resourceUri: project.root });
}
