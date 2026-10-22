import * as esbuild from "esbuild";
import { mkdir, copyFile, readFile, writeFile } from "node:fs/promises";

const thirdParties = [
  {
    "name": "yaml",
    "source": "https://github.com/eemeli/yaml",
    "attribution": "yaml by Eemeli Aro; bundled JavaScript is licensed under ISC.",
    "files": [
      "LICENSE"
    ]
  },
  {
    "name": "@vscode/python-extension",
    "source": "https://github.com/microsoft/vscode-python/tree/main/pythonExtensionApi",
    "attribution": "Python extension API by Microsoft Corporation; bundled JavaScript is licensed under MIT.",
    "files": [
      "LICENSE.md"
    ]
  },
  {
    "name": "smol-toml",
    "source": "https://github.com/squirrelchat/smol-toml",
    "attribution": "smol-toml by Squirrel Chat and contributors; bundled JavaScript is licensed under BSD-3-Clause.",
    "files": [
      "LICENSE"
    ]
  },
  {
    "name": "@vscode/codicons",
    "source": "https://github.com/microsoft/vscode-codicons",
    "attribution": "Codicons by Microsoft and contributors. The unmodified codicon.ttf icon font/content is licensed under CC-BY-4.0; codicon.css/code is licensed under MIT. The upstream content license below also retains the Git Logo attribution to Jason Long (CC-BY-3.0). No trademark rights are granted. Font/CSS are copied without modification.",
    "files": [
      "LICENSE",
      "LICENSE-CODE"
    ]
  }
];
const sections = ["WinTestKit bundled third-party notices", "License texts below are copied verbatim from the installed dependencies."];
for (const dependency of thirdParties) {
  const directory = new URL("./node_modules/" + dependency.name + "/", import.meta.url);
  const metadata = JSON.parse(await readFile(new URL("package.json", directory), "utf8"));
  sections.push(dependency.name + " " + metadata.version + "\n" + dependency.source + "\n" + dependency.attribution);
  for (const file of dependency.files) {
    const text = await readFile(new URL(file, directory), "utf8");
    if (!text.trim()) throw new Error("Empty third-party license: " + dependency.name + "/" + file);
    sections.push(dependency.name + "/" + file + "\n\n" + text);
  }
}
await mkdir(new URL("media/", import.meta.url), { recursive: true });
await writeFile(new URL("media/THIRD_PARTY_NOTICES.txt", import.meta.url), sections.join("\n\n============================================================\n\n") + "\n");

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
