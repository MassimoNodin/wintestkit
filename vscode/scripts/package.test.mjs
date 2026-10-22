import assert from "node:assert/strict";
import { test } from "node:test";
import { packageArguments, packageOptions } from "./package.mjs";

for (const noDependencies of [false, true]) {
  for (const channel of [undefined, "stable", "prerelease"]) {
    test((noDependencies ? "development" : "standard") + " channel " + String(channel), () => {
      const manifest = { version: "0.1.4" };
      const policy = { extensionVersion: "0.1.4", ...(channel ? { channel } : {}) };
      const args = packageArguments(manifest, policy, { target: "win32-arm64", output: "output.vsix", noDependencies });
      assert.equal(args.includes("--pre-release"), channel === "prerelease");
      assert.equal(args.includes("--no-dependencies"), noDependencies);
      assert.equal(args[args.indexOf("--target") + 1], "win32-arm64");
      assert.equal(args[args.indexOf("-o") + 1], "output.vsix");
      assert.deepEqual(manifest, { version: "0.1.4" });
    });
  }
}

test("default x64 and both output flags", () => {
  assert.deepEqual(packageOptions([]), { target: "win32-x64", output: undefined });
  for (const flag of ["-o", "--out"]) {
    assert.deepEqual(packageOptions(["--target", "win32-arm64", flag, "private/output.vsix"]), {
      target: "win32-arm64", output: "private/output.vsix",
    });
  }
  const args = packageArguments({ version: "0.1.1" }, { extensionVersion: "0.1.1" });
  assert.equal(args[args.indexOf("--target") + 1], "win32-x64");
});

test("invalid CLI and nonnumeric versions fail before packaging", () => {
  for (const args of [["--target"], ["--target", "linux-x64"], ["--out"], ["--publish"], ["--pre-release"]]) {
    assert.throws(() => packageOptions(args));
  }
  assert.throws(() => packageArguments({ version: "0.1.1rc1" }, { extensionVersion: "0.1.1rc1" }), /numeric/);
  assert.throws(() => packageArguments({ version: "0.1.1" }, { extensionVersion: "0.1.2" }), /match/);
});
