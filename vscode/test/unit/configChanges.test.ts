import { mkdtemp, rm, utimes, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CONFIG_FILES, ConfigChanges } from "../../src/configChanges";

describe("config change detection", () => {
  let root: string;
  let file: string;
  beforeEach(async () => {
    root = await mkdtemp(path.join(tmpdir(), "wintestkit-config-"));
    file = path.join(root, "wintestkit.yaml");
    await writeFile(file, "timeout: 10\n");
  });
  afterEach(async () => {
    await rm(root, { recursive: true, force: true });
  });

  it("ignores an event that left the content as it was", async () => {
    const changes = new ConfigChanges();
    await changes.prime(root);
    expect(await changes.changed(file)).toBe(false);
    const later = new Date(Date.now() + 60_000);
    await utimes(file, later, later); // touched by an indexer or scanner: new times, same content
    expect(await changes.changed(file)).toBe(false);
    await writeFile(file, "timeout: 10\n"); // saved again without an edit
    expect(await changes.changed(file)).toBe(false);
  });

  it("reports a real edit once, then settles", async () => {
    const changes = new ConfigChanges();
    await changes.prime(root);
    await writeFile(file, "timeout: 20\n");
    expect(await changes.changed(file)).toBe(true);
    expect(await changes.changed(file)).toBe(false);
    await writeFile(file, "timeout: 10\n"); // back to what it was is a change too
    expect(await changes.changed(file)).toBe(true);
  });

  it("treats a file it never looked at as changed, since it cannot know", async () => {
    const changes = new ConfigChanges();
    expect(await changes.changed(file)).toBe(true);
    expect(await changes.changed(file)).toBe(false);
  });

  it("notices a config file that appears or disappears", async () => {
    const changes = new ConfigChanges();
    await changes.prime(root);
    const local = path.join(root, "wintestkit.local.yaml");
    expect(await changes.changed(local)).toBe(false); // still not there: nothing happened
    await writeFile(local, "launch: attach\n");
    expect(await changes.changed(local)).toBe(true);
    await unlink(local);
    expect(await changes.changed(local)).toBe(true);
    expect(await changes.changed(local)).toBe(false);
  });

  it("primes only what has not been looked at, so a pending edit is not hidden", async () => {
    const changes = new ConfigChanges();
    await changes.prime(root);
    await writeFile(file, "timeout: 99\n");
    await changes.prime(root); // for example after the project list refreshed
    expect(await changes.changed(file)).toBe(true);
  });

  it("matches a file whatever the case or form of its path", async () => {
    const changes = new ConfigChanges();
    await changes.prime(root);
    expect(await changes.changed(path.join(root, "WinTestKit.YAML"))).toBe(false);
    expect(await changes.changed(path.join(root, ".", "wintestkit.yaml"))).toBe(false);
  });

  it("covers every file that configures a project", () => {
    expect([...CONFIG_FILES]).toEqual(["pyproject.toml", "wintestkit.yaml", "wintestkit.local.yaml", "wintestkit.local.toml"]);
  });
});
