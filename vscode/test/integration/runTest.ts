import * as path from "node:path";
import { statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import {
  downloadAndUnzipVSCode,
  resolveCliArgsFromVSCodeExecutablePath,
  runTests,
} from "@vscode/test-electron";

async function main(): Promise<void> {
  const appPath = process.env.WTK_DEMO_APP;
  if (
    !appPath ||
    !path.isAbsolute(appPath) ||
    !statSync(appPath, { throwIfNoEntry: false })?.isFile()
  ) {
    throw new Error(
      "Set WTK_DEMO_APP to an absolute path to an external legacy WTK Demo executable. No example application is bundled.",
    );
  }
  const extensionDevelopmentPath = path.resolve(__dirname, "../../..");
  const vscodeExecutablePath = await downloadAndUnzipVSCode();
  const [cli, ...cliArgs] =
    resolveCliArgsFromVSCodeExecutablePath(vscodeExecutablePath);
  const install = spawnSync(
    cli,
    [
      ...cliArgs,
      "--install-extension",
      "ms-python.python",
      "--install-extension",
      "ms-python.debugpy",
      "--force",
    ],
    { encoding: "utf8", stdio: "inherit", shell: process.platform === "win32" },
  );
  if (install.error) throw install.error;
  if (install.status !== 0)
    throw new Error("Could not install the Python extension");
  await runTests({
    vscodeExecutablePath,
    extensionDevelopmentPath,
    extensionTestsPath: path.resolve(__dirname, "suite/index"),
    extensionTestsEnv: {
      ELECTRON_RUN_AS_NODE: undefined,
      WTK_DEMO_FAILURES: "1",
      WTK_APP_PATH: appPath,
    },
    launchArgs: [
      path.resolve(extensionDevelopmentPath, "../examples/demo-tests"),
      "--disable-workspace-trust",
      "--skip-welcome",
      "--skip-release-notes",
    ],
  });
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
