import { spawnSync } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function packageOptions(args) {
  const options = { target: "win32-x64", output: undefined };
  for (let index = 0; index < args.length; index++) {
    const flag = args[index];
    if (!["--target", "-o", "--out"].includes(flag) || !args[index + 1] || args[index + 1].startsWith("-")) {
      throw new Error("Usage: package[dev] [--target win32-x64|win32-arm64] [-o|--out PATH]");
    }
    const value = args[++index];
    if (flag === "--target") options.target = value;
    else options.output = value;
  }
  if (!["win32-x64", "win32-arm64"].includes(options.target)) {
    throw new Error("Unsupported VSIX target: " + options.target);
  }
  return options;
}

export function packageArguments(manifest, policy, { target = "win32-x64", output = "dist/", noDependencies = false } = {}) {
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(manifest.version)) {
    throw new Error("VSIX manifest version must remain numeric X.Y.Z");
  }
  if (!["win32-x64", "win32-arm64"].includes(target)) {
    throw new Error("Unsupported VSIX target: " + target);
  }
  if (policy.extensionVersion !== manifest.version) {
    throw new Error("Compatibility extensionVersion must match the numeric manifest version");
  }
  const args = ["package", "--target", target, "-o", output];
  if (noDependencies) args.push("--no-dependencies");
  if (policy.channel === "prerelease") args.push("--pre-release");
  return args;
}

export async function packageExtension(args = process.argv.slice(2)) {
  const root = fileURLToPath(new URL("../", import.meta.url));
  const options = packageOptions(args);
  const manifest = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
  const policy = JSON.parse(await readFile(path.join(root, "src/compatibility.json"), "utf8"));
  const command = packageArguments(manifest, policy, options);
  await mkdir(path.join(root, "dist"), { recursive: true });
  const result = spawnSync(process.execPath, [path.join(root, "node_modules/@vscode/vsce/vsce"), ...command], {
    cwd: root,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error("VSIX packaging failed");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await packageExtension();
}
