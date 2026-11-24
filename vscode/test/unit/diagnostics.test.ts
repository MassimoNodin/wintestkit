import { describe, expect, it } from "vitest";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { inflateRawSync } from "node:zlib";
import { collect } from "../../src/diagnostics/collect";
import { LIMIT, redact, redactSecrets, truncate } from "../../src/diagnostics/redact";
import { crc32, zip } from "../../src/diagnostics/zip";

const ids = { user: "Alice", computer: ["HOST", "HOST2"], domain: "CORP", home: "C:\\Users\\Alice" };
describe("diagnostics", () => {
  it("redacts identities, all home forms and counts case-insensitively", () => {
    const counts: Record<string, number> = {};
    const input = ['c:\\users\\ALICE', 'C:/Users/Alice', 'C:\\\\Users\\\\Alice', 'alice HOST host2 corp a@example.com'].join(' ');
    expect(redact(input, ids, counts)).toBe('<home> <home> <home> <user> <computer> <computer> <domain> <email>');
    expect(counts).toEqual({ home: 3, user: 1, computer: 2, domain: 1, email: 1 });
  });
  it("redacts nested secret keys and bounds UTF-8 text", () => {
    expect(redactSecrets({ accessToken: 'x', nested: [{ password: 'p', ok: 'v' }] })).toEqual({ accessToken: '<redacted>', nested: [{ password: '<redacted>', ok: 'v' }] });
    const text = truncate('é'.repeat(LIMIT));
    expect(text).toMatch(/^\[Truncated/); expect(Buffer.byteLength(text)).toBeLessThanOrEqual(LIMIT); expect(text.endsWith('é')).toBe(true);
  });
  it("isolates failures and records redacted contents and hashes", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), 'wtk-test-'));
    try {
      await collect(dir, { interpreter: 'C:\\Users\\Alice\\python.exe' }, 'Alice', [
        { name: 'broken', run: async () => { throw new Error('HOST failed'); } },
        { name: 'good', run: async () => ({ 'logs/a.log': 'Alice' }) },
      ], ids, new Date('2025-01-01T00:00:00Z'));
      const manifest = JSON.parse(await readFile(path.join(dir, 'manifest.json'), 'utf8'));
      expect(manifest.schemaVersion).toBe(1); expect(manifest.files[0]).toMatchObject({ path: 'logs/a.log', size: 6 });
      expect(manifest.files[0].sha256).toMatch(/^[a-f0-9]{64}$/); expect(manifest.failures.broken).toContain('<computer>'); expect(manifest.summary.interpreter).toBe('<home>\\python.exe');
      expect(await readFile(path.join(dir, 'logs/a.log'), 'utf8')).toBe('<user>');
    } finally { await rm(dir, { recursive: true, force: true }); }
  });
  it("writes ZIP entries readable from the central directory", () => {
    const archive = zip([{ name: 'a.txt', data: Buffer.from('hello') }, { name: 'logs/é.txt', data: Buffer.from('world') }]);
    const end = archive.length - 22, count = archive.readUInt16LE(end + 10); let pos = archive.readUInt32LE(end + 16);
    const entries: Record<string, string> = {};
    for (let i = 0; i < count; i++) {
      expect(archive.readUInt32LE(pos)).toBe(0x02014b50);
      const size = archive.readUInt32LE(pos + 20), nameLength = archive.readUInt16LE(pos + 28), extra = archive.readUInt16LE(pos + 30), comment = archive.readUInt16LE(pos + 32), offset = archive.readUInt32LE(pos + 42);
      const name = archive.subarray(pos + 46, pos + 46 + nameLength).toString();
      const start = offset + 30 + archive.readUInt16LE(offset + 26) + archive.readUInt16LE(offset + 28);
      const data = inflateRawSync(archive.subarray(start, start + size));
      expect(crc32(data)).toBe(archive.readUInt32LE(pos + 16)); entries[name] = data.toString(); pos += 46 + nameLength + extra + comment;
    }
    expect(entries).toEqual({ 'a.txt': 'hello', 'logs/é.txt': 'world' });
  });
});
