import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";

let notices: string;
beforeAll(() => {
  execFileSync(process.execPath, ["esbuild.mjs"], { windowsHide: true, stdio: "pipe" });
  notices = readFileSync("media/THIRD_PARTY_NOTICES.txt", "utf8");
});

describe("bundled third-party notices", () => {
  it("routes local standard packaging through the channel-aware helper", () => {
    const manifest = JSON.parse(readFileSync("package.json", "utf8")) as { scripts: { package: string } };
    expect(manifest.scripts.package).toBe("npm run build && node scripts/package.mjs");
  });
  it.each([
    ["yaml", "LICENSE"],
    ["@vscode/python-extension", "LICENSE.md"],
    ["smol-toml", "LICENSE"],
    ["@vscode/codicons", "LICENSE"],
    ["@vscode/codicons", "LICENSE-CODE"],
  ])("retains the complete installed %s/%s license and package version", (dependency, file) => {
    const directory = "node_modules/" + dependency + "/";
    expect(notices).toContain(readFileSync(directory + file, "utf8"));
    const metadata = JSON.parse(readFileSync(directory + "package.json", "utf8")) as { version: string };
    expect(notices).toContain(dependency + " " + metadata.version);
  });
  it("distinguishes Codicons font/content and code, preserving additional attribution", () => {
    expect(notices).toContain("codicon.ttf icon font/content is licensed under CC-BY-4.0");
    expect(notices).toContain("codicon.css/code is licensed under MIT");
    expect(notices).toContain("Git Logo by [Jason Long]");
    expect(notices).toContain("https://creativecommons.org/licenses/by/3.0/");
    expect(notices).toContain("https://github.com/microsoft/vscode-codicons");
    expect(notices).toContain("copied without modification");
  });
  it("includes the notices with packaged files even though node_modules is excluded", () => {
    const files = execFileSync(process.execPath, ["node_modules/@vscode/vsce/vsce", "ls"], {
      encoding: "utf8", windowsHide: true, stdio: ["ignore", "pipe", "pipe"], timeout: 25000,
    }).replaceAll("\\", "/").split(/\r?\n/);
    expect(files).toContain("media/THIRD_PARTY_NOTICES.txt");
    expect(files).toContain("media/codicons/codicon.css");
    expect(files).toContain("media/codicons/codicon.ttf");
    expect(files.some((file) => file.startsWith("node_modules/"))).toBe(false);
  }, 30000);
});
