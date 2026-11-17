import { createWriteStream, type WriteStream } from "node:fs";

const omitted = new Set(["properties", "dataUrl", "image", "rect", "patterns", "runtimeId"]);

export class SpyTrace {
  private stream?: WriteStream;

  configure(file: string): void {
    try {
      this.stream?.end();
      this.stream = undefined;
      if (!file) return;
      const stream = createWriteStream(file, { flags: "a" });
      stream.on("error", () => {
        if (this.stream === stream) this.stream = undefined;
      });
      this.stream = stream;
    } catch {
      this.stream = undefined;
    }
  }

  message(dir: "toWebview" | "toHost", msg: unknown): void {
    this.write({ t: Date.now(), dir, msg });
  }

  rpc(method: string, nodeId?: string): void {
    this.write({ t: Date.now(), dir: "rpc", method, params: nodeId === undefined ? {} : { nodeId } });
  }

  private write(entry: unknown): void {
    if (!this.stream) return;
    try {
      const line = JSON.stringify(entry, (key, value: unknown) => {
        if (omitted.has(key) || key.toLowerCase().endsWith("dataurl") || key === "suggestion") return undefined;
        return typeof value === "string" && value.length > 500 ? value.slice(0, 500) : value;
      });
      this.stream.write(line + "\n");
    } catch {
      return;
    }
  }

  dispose(): void {
    try { this.stream?.end(); } catch { return; }
    this.stream = undefined;
  }
}
