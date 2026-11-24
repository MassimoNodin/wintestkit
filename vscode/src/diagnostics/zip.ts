import { deflateRawSync } from "node:zlib";

export function crc32(data: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of data) { crc ^= byte; for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)); }
  return (crc ^ 0xffffffff) >>> 0;
}
export function zip(files: { name: string; data: Buffer }[]): Buffer {
  const local: Buffer[] = [], central: Buffer[] = [];
  let offset = 0;
  for (const file of files) {
    const name = Buffer.from(file.name), compressed = deflateRawSync(file.data), crc = crc32(file.data);
    const h = Buffer.alloc(30); h.writeUInt32LE(0x04034b50, 0); h.writeUInt16LE(20, 4); h.writeUInt16LE(0x800, 6); h.writeUInt16LE(8, 8); h.writeUInt32LE(crc, 14); h.writeUInt32LE(compressed.length, 18); h.writeUInt32LE(file.data.length, 22); h.writeUInt16LE(name.length, 26);
    local.push(h, name, compressed);
    const c = Buffer.alloc(46); c.writeUInt32LE(0x02014b50, 0); c.writeUInt16LE(20, 4); c.writeUInt16LE(20, 6); c.writeUInt16LE(0x800, 8); c.writeUInt16LE(8, 10); c.writeUInt32LE(crc, 16); c.writeUInt32LE(compressed.length, 20); c.writeUInt32LE(file.data.length, 24); c.writeUInt16LE(name.length, 28); c.writeUInt32LE(offset, 42); central.push(c, name);
    offset += h.length + name.length + compressed.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(files.length, 8); end.writeUInt16LE(files.length, 10); end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, directory, end]);
}
