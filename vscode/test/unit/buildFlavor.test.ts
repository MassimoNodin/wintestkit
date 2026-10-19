import { build } from "esbuild";
import { describe, expect, it } from "vitest";

describe("package build isolation", () => {
  it("removes local package installation code from the production bundle", async () => {
    const bundle = async (development: boolean) => {
      const result = await build({
        entryPoints: ["src/extension.ts"], bundle: true, platform: "node", format: "cjs",
        target: "node20", external: ["vscode"], write: false, minifySyntax: true,
        define: { __WTK_DEV__: String(development) },
      });
      return result.outputFiles[0].text;
    };
    const production = await bundle(false);
    const development = await bundle(true);
    for (const marker of ["development.packageSource.", "Use local wheel", "Development: select a trusted WinTestKit wheel", "Back Up and Reset", "wintestkit-reset-"]) {
      expect(production).not.toContain(marker);
      expect(development).toContain(marker);
    }
    expect(production).not.toContain("Install the local WinTestKit package in editable mode?");
  });
});
