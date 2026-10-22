import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import * as path from "node:path";

/** The files whose contents configure a project; a real change to one restarts its server. */
export const CONFIG_FILES = [
  "pyproject.toml",
  "wintestkit.yaml",
  "wintestkit.local.yaml",
  "wintestkit.local.toml",
] as const;

const missing = "missing";

async function fingerprint(file: string): Promise<string> {
  try {
    return createHash("sha256").update(await readFile(file)).digest("hex");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return missing;
    // Unreadable right now (for example mid-write): count it as a change rather than hide one.
    return "unreadable:" + Date.now() + Math.random();
  }
}

/**
 * Tells a real edit of a config file from an event that left its content as it was.
 *
 * File watchers also report a file that an indexer, scanner or sync client merely touched, as
 * happens here about once an hour. Restarting the server for that interrupts whatever the user is
 * doing for nothing, so a file counts as changed only when what it contains is different from
 * the last time it was looked at.
 */
export class ConfigChanges {
  private readonly seen = new Map<string, string>();

  private static key(file: string): string {
    return path.resolve(file).toLowerCase();
  }

  /** Records what a project's config files contain now, unless they have been looked at already. */
  async prime(root: string): Promise<void> {
    await Promise.all(
      CONFIG_FILES.map(async (name) => {
        const file = path.join(root, name);
        const key = ConfigChanges.key(file);
        if (!this.seen.has(key)) this.seen.set(key, await fingerprint(file));
      }),
    );
  }

  /** Whether ``file`` now holds something different from when it was last looked at. */
  async changed(file: string): Promise<boolean> {
    const key = ConfigChanges.key(file);
    const now = await fingerprint(file);
    const before = this.seen.get(key);
    this.seen.set(key, now);
    return before === undefined || before !== now;
  }
}
