import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import * as path from "node:path";

const manifestLimit = 64 * 1024;
const imageLimit = 16 * 1024 * 1024;
const dimensionLimit = 16384;

export interface ObjectPreview {
  definitionId: string;
  captureId: string;
  capturedAt: string;
  locatorFingerprint: string;
  width: number;
  height: number;
  cropDataUrl: string;
}

export function definitionPreviewKey(definitionId: string): string {
  const parts = definitionId.split("::");
  const file = parts[0];
  if (definitionId.length > 2048 || parts.length !== 2 || !file ||
    file.includes("\\") || file.includes(":") || file.includes("\0") ||
    path.posix.isAbsolute(file) || path.posix.normalize(file) !== file ||
    file.split("/").some((part) => !part || part === "." || part === "..") ||
    !/^[\p{ID_Start}_][\p{ID_Continue}]*(?:\.(?:<locals>|[\p{ID_Start}_][\p{ID_Continue}]*))+$/u.test(parts[1]))
    throw new Error("Invalid canonical definition ID.");
  return createHash("sha256").update(definitionId, "utf8").digest("hex");
}

function contained(root: string, target: string): boolean {
  const relative = path.relative(root, target);
  return relative !== ".." && !relative.startsWith(".." + path.sep) && !path.isAbsolute(relative);
}

async function checkedPath(root: string, segments: string[], limit?: number): Promise<string> {
  let target = root;
  for (let index = 0; index < segments.length; index++) {
    target = path.join(target, segments[index]);
    const stat = await lstat(target);
    const last = index === segments.length - 1;
    if (stat.isSymbolicLink() || (!last && !stat.isDirectory()) ||
      (last && limit !== undefined && (!stat.isFile() || stat.size < 1 || stat.size > limit)) ||
      !contained(root, await realpath(target)))
      throw new Error("Unsafe saved preview path or size.");
  }
  return target;
}

async function boundedRead(root: string, file: string, limit: number): Promise<Buffer> {
  const handle = await open(file, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size < 1 || stat.size > limit) throw new Error("Saved preview exceeds its size limit.");
    const buffer = Buffer.alloc(stat.size + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const { bytesRead } = await handle.read(buffer, offset, buffer.length - offset, offset);
      if (!bytesRead) break;
      offset += bytesRead;
    }
    const current = await lstat(file);
    if (offset !== stat.size || current.isSymbolicLink() || current.ino !== stat.ino || current.dev !== stat.dev ||
      !contained(root, await realpath(file))) throw new Error("Saved preview changed while reading.");
    return buffer.subarray(0, offset);
  } finally {
    await handle.close();
  }
}

export function validatePreviewWebp(bytes: Buffer, width: number, height: number): void {
  if (bytes.length < 20 || bytes.length > imageLimit || bytes.toString("ascii", 0, 4) !== "RIFF" ||
    bytes.toString("ascii", 8, 12) !== "WEBP" || bytes.readUInt32LE(4) + 8 !== bytes.length)
    throw new Error("Invalid saved WebP image.");
  let offset = 12;
  let frame = false;
  while (offset + 8 <= bytes.length) {
    const kind = bytes.toString("ascii", offset, offset + 4);
    const length = bytes.readUInt32LE(offset + 4);
    const start = offset + 8;
    if (start + length + (length % 2) > bytes.length || kind === "ANIM" || kind === "ANMF")
      throw new Error("Invalid or animated saved WebP image.");
    let actualWidth: number | undefined;
    let actualHeight: number | undefined;
    if (kind === "VP8X") {
      if (length !== 10 || (bytes[start] & 2)) throw new Error("Invalid saved WebP canvas.");
      actualWidth = bytes.readUIntLE(start + 4, 3) + 1;
      actualHeight = bytes.readUIntLE(start + 7, 3) + 1;
    } else if (kind === "VP8 ") {
      if (frame || length <= 10 || (bytes[start] & 1) || bytes.toString("hex", start + 3, start + 6) !== "9d012a")
        throw new Error("Invalid saved WebP frame.");
      actualWidth = bytes.readUInt16LE(start + 6) & 0x3fff;
      actualHeight = bytes.readUInt16LE(start + 8) & 0x3fff;
      frame = true;
    } else if (kind === "VP8L") {
      if (frame || length <= 5 || bytes[start] !== 0x2f || (bytes[start + 4] & 0xe0))
        throw new Error("Invalid saved lossless WebP frame.");
      const bits = bytes.readUInt32LE(start + 1);
      actualWidth = (bits & 0x3fff) + 1;
      actualHeight = ((bits >>> 14) & 0x3fff) + 1;
      frame = true;
    }
    if (actualWidth !== undefined && (actualWidth !== width || actualHeight !== height))
      throw new Error("Saved preview dimensions do not match its manifest.");
    offset = start + length + (length % 2);
  }
  if (!frame || offset !== bytes.length) throw new Error("Saved preview has no complete WebP frame.");
}

export async function readObjectPreview(projectRoot: string, definitionId: string): Promise<ObjectPreview | undefined> {
  const key = definitionPreviewKey(definitionId);
  const root = await realpath(projectRoot);
  let manifestPath: string;
  try {
    manifestPath = await checkedPath(root, ["object-previews", key, "manifest.json"], manifestLimit);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  const manifest = JSON.parse((await boundedRead(root, manifestPath, manifestLimit)).toString("utf8")) as Record<string, unknown>;
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest) ||
    manifest.schemaVersion !== 1 || manifest.definitionId !== definitionId ||
    typeof manifest.captureId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(manifest.captureId) ||
    typeof manifest.capturedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)$/.test(manifest.capturedAt) ||
    !Number.isFinite(Date.parse(manifest.capturedAt)) ||
    new Date(manifest.capturedAt).toISOString().slice(0, 19) !== manifest.capturedAt.slice(0, 19) ||
    typeof manifest.locatorFingerprint !== "string" || !manifest.locatorFingerprint || manifest.locatorFingerprint.length > 2048 ||
    manifest.crop !== manifest.captureId + ".element.webp" || manifest.window !== manifest.captureId + ".window.webp" ||
    !Number.isInteger(manifest.width) || !Number.isInteger(manifest.height) ||
    (manifest.width as number) < 1 || (manifest.height as number) < 1 ||
    (manifest.width as number) > dimensionLimit || (manifest.height as number) > dimensionLimit ||
    (manifest.width as number) * (manifest.height as number) > 64 * 1024 * 1024)
    throw new Error("Invalid saved preview manifest.");
  const cropPath = await checkedPath(root, ["object-previews", key, manifest.crop as string], imageLimit);
  await checkedPath(root, ["object-previews", key, manifest.window as string], imageLimit);
  const crop = await boundedRead(root, cropPath, imageLimit);
  validatePreviewWebp(crop, manifest.width as number, manifest.height as number);
  return {
    definitionId, captureId: manifest.captureId, capturedAt: manifest.capturedAt,
    locatorFingerprint: manifest.locatorFingerprint,
    width: manifest.width as number, height: manifest.height as number,
    cropDataUrl: "data:image/webp;base64," + crop.toString("base64"),
  };
}
