export interface StatusAction {
  label: string;
  command: string;
}

export function statusMenuActions(running: boolean): StatusAction[] {
  return [
    ...(running
      ? [
          { label: "Restart App", command: "wintestkit.restartApp" },
          { label: "Close App", command: "wintestkit.closeApp" },
        ]
      : [{ label: "Launch App", command: "wintestkit.launchApp" }]),
    { label: "Run all tests", command: "testing.runAll" },
    { label: "Open Testing view", command: "wintestkit.openTesting" },
    { label: "Restart Server", command: "wintestkit.restartServer" },
    { label: "Open Last Report", command: "wintestkit.openReport" },
    { label: "Check Environment", command: "wintestkit.runDoctor" },
    { label: "Show Output", command: "wintestkit.showOutput" },
  ];
}

export async function runStatusMenu(
  actions: StatusAction[],
  choose: (actions: StatusAction[]) => PromiseLike<StatusAction | undefined>,
  execute: (command: string) => PromiseLike<unknown>,
): Promise<void> {
  const choice = await choose(actions);
  if (choice) await execute(choice.command);
}
