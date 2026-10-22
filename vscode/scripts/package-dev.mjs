import { cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { packageArguments, packageOptions } from "./package.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const options = packageOptions(process.argv.slice(2));
const policy = JSON.parse(await readFile(path.join(root, "src/compatibility.json"), "utf8"));
const stage = await mkdtemp(path.join(tmpdir(), "wintestkit-dev-"));
const manifest = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
const run = (args, cwd) => {
  const result = spawnSync(process.execPath, args, { cwd, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error("Development packaging failed: " + args.join(" "));
};
await mkdir(path.join(stage, "dist"), { recursive: true });
run(["esbuild.mjs", "--dev", "--outfile=" + path.join(stage, "dist/extension.js")], root);
for (const name of ["media", "README.md", "LICENSE", "CHANGELOG.md"])
  await cp(path.join(root, name), path.join(stage, name), { recursive: true });
manifest.displayName = manifest.displayName + " (Development)";
manifest.contributes.commands.push({
  command: "wintestkit.dev.resetRepository",
  title: "Development: Reset Repository and Introduction",
  category: "WinTestKit",
});
manifest.description = "Development build: permits explicitly selected local Python wheels. " + manifest.description;
delete manifest.scripts;
delete manifest.dependencies;
delete manifest.devDependencies;
await writeFile(path.join(stage, "package.json"), JSON.stringify(manifest, null, 2) + "\n");
await writeFile(path.join(stage, ".vscodeignore"), "dist/*.map\n");
await mkdir(path.join(root, "dist"), { recursive: true });
const output = path.resolve(root, options.output ?? path.join("dist", "wintestkit-dev-" + options.target + "-" + manifest.version + ".vsix"));
run([path.join(root, "node_modules/@vscode/vsce/vsce"), ...packageArguments(manifest, policy, { ...options, output, noDependencies: true })], stage);
console.log("Development VSIX: " + output);
