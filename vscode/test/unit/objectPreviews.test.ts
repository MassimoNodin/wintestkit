import { createHash } from "node:crypto";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { definitionPreviewKey, livePreviewImages, readObjectPreview, validatePreviewWebp } from "../../src/spy/objectPreviews";

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
    schemaVersion: 2, definitionId, captureId: "test-123",
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

  it("returns the crop and the outlined window with the original check timestamp", async () => {
    const { root } = await fixture();
    const preview = await readObjectPreview(root, definitionId);
    const url = "data:image/webp;base64," + image.toString("base64");
    expect(preview).toMatchObject({ definitionId, capturedAt: "2026-10-20T12:34:56.000Z", width: 1, height: 1,
      cropDataUrl: url, windowDataUrl: url });
  });

  it("rejects a saved window image that is not a still WebP", async () => {
    const { root, directory } = await fixture();
    await writeFile(path.join(directory, "test-123.window.webp"), Buffer.from("not an image at all, really"));
    await expect(readObjectPreview(root, definitionId)).rejects.toThrow();
  });

  it("still fails when the images the manifest names are really gone", async () => {
    const { root, directory } = await fixture();
    await rm(path.join(directory, "test-123.element.webp"));
    await expect(readObjectPreview(root, definitionId)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("returns unavailable when the manifest has not been recorded", async () => {
    const { root } = await fixture();
    expect(await readObjectPreview(root, "pages/Login.py::LoginPage.cancel")).toBeUndefined();
  });

  it("does not display legacy automatic test captures as intentional checks", async () => {
    const { root } = await fixture({ schemaVersion: 1 });
    expect(await readObjectPreview(root, definitionId)).toBeUndefined();
  });

  it("accepts the backend's microsecond ISO UTC offset without rewriting capture time", async () => {
    const capturedAt = "2026-10-20T12:34:56.123456+00:00";
    const { root } = await fixture({ capturedAt });
    expect((await readObjectPreview(root, definitionId))?.capturedAt).toBe(capturedAt);
  });

  it.each([
    { schemaVersion: 3 }, { definitionId: "pages/Other.py::Other.submit" },
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

describe("live preview results", () => {
  const entry = { data: image.toString("base64"), width: 1, height: 1 };
  it("turns a valid capture into data URLs for the webview", () => {
    const url = "data:image/webp;base64," + entry.data;
    expect(livePreviewImages({ element: entry, window: entry })).toEqual({ elementDataUrl: url, windowDataUrl: url });
  });
  it("passes the reason through when there is nothing to show", () => {
    expect(livePreviewImages({ reason: "The window cannot be captured." })).toBe("The window cannot be captured.");
  });
  it.each([
    undefined, null, "text", {}, { element: entry }, { element: entry, window: { ...entry, data: "not base64!" } },
    { element: entry, window: { ...entry, width: 2 } }, { element: entry, window: { ...entry, data: "AAAA" } },
    { element: entry, window: { data: entry.data, width: 1.5, height: 1 } },
  ])("rejects a malformed result %#", (value) => {
    expect(typeof livePreviewImages(value)).toBe("string");
  });
});
