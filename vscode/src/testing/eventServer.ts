import * as net from "node:net";
import type { RunEvent } from "../protocol/generated";
import { LineSplitter } from "../server/jsonrpc";

export class EventServer {
  private readonly server = net.createServer((socket) => this.accept(socket));
  private socket?: net.Socket;
  private accepted = false;
  private disposed = false;
  private resolveDrain?: () => void;
  private readonly drained = new Promise<void>((resolve) => {
    this.resolveDrain = resolve;
  });
  constructor(
    private readonly event: (event: RunEvent) => void,
    private readonly error: (error: unknown) => void,
  ) {}
  async listen(): Promise<string> {
    await new Promise<void>((resolve, reject) => {
      this.server.once("error", reject);
      this.server.listen(0, "127.0.0.1", () => {
        this.server.removeListener("error", reject);
        resolve();
      });
    });
    this.server.on("error", this.error);
    const address = this.server.address();
    if (!address || typeof address === "string")
      throw new Error("Event listener has no TCP address");
    return "tcp://127.0.0.1:" + address.port;
  }
  private accept(socket: net.Socket): void {
    if (this.accepted || this.disposed) {
      socket.destroy();
      return;
    }
    this.accepted = true;
    this.socket = socket;
    let bytes = 0;
    const splitter = new LineSplitter((line) => {
      bytes = 0;
      try {
        const value: unknown = JSON.parse(line);
        if (
          !value ||
          typeof value !== "object" ||
          !("event" in value) ||
          typeof value.event !== "string"
        )
          throw new Error("Invalid test event");
        this.event(value as RunEvent);
      } catch (error) {
        this.error(error);
      }
    });
    socket.on("data", (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > 8 * 1024 * 1024) {
        this.error(new Error("Test event exceeded 8 MiB"));
        socket.destroy();
        return;
      }
      splitter.push(chunk);
    });
    socket.on("error", this.error);
    socket.on("end", () => splitter.end());
    socket.on("close", () => this.resolveDrain?.());
  }
  async drain(): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    await Promise.race([
      this.drained,
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, 250);
      }),
    ]);
    if (timer) clearTimeout(timer);
  }
  dispose(): void {
    this.disposed = true;
    this.socket?.destroy();
    if (this.server.listening) this.server.close();
    this.resolveDrain?.();
  }
}
