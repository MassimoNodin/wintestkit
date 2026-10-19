import * as esbuild from "esbuild";
import { mkdir, copyFile } from "node:fs/promises";

await mkdir("media/codicons", { recursive: true });
for (const file of ["codicon.css", "codicon.ttf"])
  await copyFile(
    "node_modules/@vscode/codicons/dist/" + file,
    "media/codicons/" + file,
  );

// The report page is the Python package's template; the panel fills it from results.json.
await mkdir("media/report", { recursive: true });
await copyFile(
  "../python/src/wintestkit/report/template.html",
  "media/report/template.html",
);

const options = {
  define: { __WTK_DEV__: String(process.argv.includes("--dev")) },
  minifySyntax: true,
  entryPoints: ["src/extension.ts"],
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["vscode"],
  outfile: process.argv.find((arg) => arg.startsWith("--outfile="))?.slice(10) ?? "dist/extension.js",
  sourcemap: true,
  logLevel: "info",
};

if (process.argv.includes("--watch")) {
  const context = await esbuild.context(options);
  await context.watch();
} else {
  await esbuild.build(options);
}
