import { StringDecoder } from "node:string_decoder";

export interface Disposable {
  dispose(): void;
}
export class RpcError extends Error {
  constructor(
    public readonly code: number,
    message: string,
    public readonly data?: unknown,
  ) {
    super(message);
    this.name = "RpcError";
  }
}

export class LineSplitter {
  private readonly decoder = new StringDecoder("utf8");
  private buffered = "";
  constructor(private readonly onLine: (line: string) => void) {}
  push(chunk: Buffer | string): void {
    this.buffered +=
      typeof chunk === "string" ? chunk : this.decoder.write(chunk);
    let newline: number;
    while ((newline = this.buffered.indexOf("\n")) >= 0) {
      const line = this.buffered.slice(0, newline).replace(/\r$/, "");
      this.buffered = this.buffered.slice(newline + 1);
      if (line.trim()) this.onLine(line);
    }
  }
  end(): void {
    this.push(this.decoder.end());
    if (this.buffered.trim()) this.onLine(this.buffered.replace(/\r$/, ""));
    this.buffered = "";
  }
}

interface Pending {
  resolve: (result: unknown) => void;
  reject: (error: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class JsonRpcClient implements Disposable {
  private nextId = 0;
  private stopped = false;
  private readonly pending = new Map<number, Pending>();
  private readonly notifications = new Map<
    string,
    Set<(params: unknown) => void>
  >();
  constructor(private readonly write: (line: string) => void) {}
  request<Result>(
    method: string,
    params: unknown = {},
    timeoutMs = 30000,
  ): Promise<Result> {
    if (this.stopped) return Promise.reject(new RpcError(-1, "server stopped"));
    const requestId = ++this.nextId;
    return new Promise<Result>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new RpcError(-1, `request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(requestId, {
        resolve: (value) => resolve(value as Result),
        reject,
        timer,
      });
      try {
        this.write(
          JSON.stringify({ jsonrpc: "2.0", id: requestId, method, params }) +
            "\n",
        );
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(requestId);
        reject(error);
      }
    });
  }
  handleLine(line: string): void {
    let message: unknown;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (!message || typeof message !== "object" || Array.isArray(message))
      return;
    const response = message as Record<string, unknown>;
    if (response.jsonrpc !== "2.0") return;
    if (typeof response.id === "number") {
      const pending = this.pending.get(response.id);
      if (!pending) return;
      this.pending.delete(response.id);
      clearTimeout(pending.timer);
      if (response.error && typeof response.error === "object") {
        const error = response.error as Record<string, unknown>;
        pending.reject(
          new RpcError(
            typeof error.code === "number" ? error.code : -32603,
            String(error.message ?? "RPC error"),
            error.data,
          ),
        );
      } else if ("result" in response) pending.resolve(response.result);
      else pending.reject(new RpcError(-32603, "invalid RPC response"));
    } else if (typeof response.method === "string") {
      for (const handler of this.notifications.get(response.method) ?? []) {
        try {
          handler(response.params);
        } catch {
          continue;
        }
      }
    }
  }
  onNotification(
    method: string,
    handler: (params: unknown) => void,
  ): Disposable {
    const handlers = this.notifications.get(method) ?? new Set();
    this.notifications.set(method, handlers);
    handlers.add(handler);
    return {
      dispose: () => {
        handlers.delete(handler);
        if (!handlers.size) this.notifications.delete(method);
      },
    };
  }
  dispose(): void {
    this.stopped = true;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new RpcError(-1, "server stopped"));
    }
    this.pending.clear();
    this.notifications.clear();
  }
}
