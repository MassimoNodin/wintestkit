import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { definitionPreviewKey, readObjectPreview, validatePreviewWebp } from "../../src/spy/objectPreviews";

const definitionId = "pages/Login.py::LoginPage.submit";
const image = Buffer.from("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==", "base64");
const temporary: string[] = [];

afterEach(async () => {
  await Promise.all(temporary.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

async function fixture(overrides: Record<string, unknown> = {}) {
  const root = await mkdtemp(path.join(tmpdir(), "wintestkit-previews-"));
  temporary.push(root);
  const directory = path.join(root, "object-previews", definitionPreviewKey(definitionId));
  await mkdir(directory, { recursive: true });
  const manifest = {
    schemaVersion: 1, definitionId, captureId: "test-123",
    capturedAt: "2026-10-20T12:34:56.000Z", locatorFingerprint: "fingerprint",
    crop: "test-123.element.webp", window: "test-123.window.webp", width: 1, height: 1,
    context: { test: "test_login" }, ...overrides,
  };
  await writeFile(path.join(directory, "manifest.json"), JSON.stringify(manifest));
  await writeFile(path.join(directory, "test-123.element.webp"), image);
  await writeFile(path.join(directory, "test-123.window.webp"), image);
  return { root, directory, manifest };
}

describe("saved definition object previews", () => {
  it("hashes the case-preserved UTF-8 canonical ID", () => {
    expect(definitionPreviewKey(definitionId)).toBe(createHash("sha256").update(definitionId, "utf8").digest("hex"));
    expect(definitionPreviewKey(definitionId.toLowerCase())).not.toBe(definitionPreviewKey(definitionId));
    const unicodeId = "pages/Caf\u00e9.py::Outer.Inner.submit";
    expect(definitionPreviewKey(unicodeId)).toBe(createHash("sha256").update(unicodeId, "utf8").digest("hex"));
  });

  it.each(["../Login.py::Login.submit", "/Login.py::Login.submit", "C:/Login.py::Login.submit",
    "pages\\Login.py::Login.submit", "pages/./Login.py::Login.submit", "pages//Login.py::Login.submit",
    "pages/Login.py::submit", "pages/Login.py::Login.submit::extra"])("rejects noncanonical ID %s", (id) => {
    expect(() => definitionPreviewKey(id)).toThrow("canonical");
  });

  it("returns only the crop and original last-test timestamp, retaining the full window on disk", async () => {
    const { root, directory } = await fixture();
    const preview = await readObjectPreview(root, definitionId);
    expect(preview).toMatchObject({ definitionId, capturedAt: "2026-10-20T12:34:56.000Z", width: 1, height: 1,
      cropDataUrl: "data:image/webp;base64," + image.toString("base64") });
    expect(preview).not.toHaveProperty("window");
    expect(preview).not.toHaveProperty("windowDataUrl");
    expect(await readFile(path.join(directory, "test-123.window.webp"))).toEqual(image);
  });

  it("returns unavailable when the manifest has not been recorded", async () => {
    const { root } = await fixture();
    expect(await readObjectPreview(root, "pages/Login.py::LoginPage.cancel")).toBeUndefined();
  });

  it("accepts the backend's microsecond ISO UTC offset without rewriting capture time", async () => {
    const capturedAt = "2026-10-20T12:34:56.123456+00:00";
    const { root } = await fixture({ capturedAt });
    expect((await readObjectPreview(root, definitionId))?.capturedAt).toBe(capturedAt);
  });

  it.each([
    { schemaVersion: 2 }, { definitionId: "pages/Other.py::Other.submit" },
    { captureId: "../escape" }, { crop: "../test-123.element.webp" },
    { window: "C:/outside.webp" }, { crop: "other.element.webp" },
    { capturedAt: "2026-10-20T12:34:56+10:00" }, { locatorFingerprint: "" },
    { width: 0 }, { height: 20000 }, { width: 2 },
  ])("rejects a mismatched or unsafe manifest %j", async (overrides) => {
    const { root } = await fixture(overrides);
    await expect(readObjectPreview(root, definitionId)).rejects.toThrow();
  });

  it("rejects oversized manifests and crop images before reading their contents", async () => {
    const { root, directory } = await fixture();
    await writeFile(path.join(directory, "manifest.json"), " ".repeat(65537));
    await expect(readObjectPreview(root, definitionId)).rejects.toThrow("size");
    const next = await fixture();
    await writeFile(path.join(next.directory, "test-123.element.webp"), Buffer.alloc(16 * 1024 * 1024 + 1));
    await expect(readObjectPreview(next.root, definitionId)).rejects.toThrow("size");
  });

  it("rejects a directory junction or symlink escaping the project", async () => {
    const { root, directory } = await fixture();
    const outside = await mkdtemp(path.join(tmpdir(), "wintestkit-preview-outside-"));
    temporary.push(outside);
    await rm(directory, { recursive: true });
    await symlink(outside, directory, process.platform === "win32" ? "junction" : "dir");
    await expect(readObjectPreview(root, definitionId)).rejects.toThrow("Unsafe");
  });

  it("rejects truncated, wrong-format, and wrong-dimension crop images", () => {
    expect(() => validatePreviewWebp(image, 1, 1)).not.toThrow();
    expect(() => validatePreviewWebp(image.subarray(0, 20), 1, 1)).toThrow();
    expect(() => validatePreviewWebp(Buffer.from("<svg onload='unsafe'/>"), 1, 1)).toThrow();
    expect(() => validatePreviewWebp(image, 2, 1)).toThrow("dimensions");
  });
});
