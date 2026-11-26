import { StringDecoder } from "node:string_decoder";
import { randomBytes } from "node:crypto";

/** A validated JSON number whose original text must survive JavaScript serialization. */
export class RpcNumber {
  constructor(readonly text: string) {
    if (text.length > 4096 || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(text)) throw new Error("Invalid number");
  }
}
function serialize(value: unknown): string {
  const prefix = `__wtk_number_${randomBytes(16).toString("hex")}_`;
  const numbers: string[] = [];
  const json = JSON.stringify(value, (_key, item: unknown) => {
    if (!(item instanceof RpcNumber)) return item;
    const marker = prefix + numbers.length + "__";
    numbers.push(item.text);
    return marker;
  });
  return json.replace(new RegExp(`"${prefix}(\\d+)__"`, "g"), (_match, index: string) => numbers[Number(index)]);
}

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
  background: boolean;
}

export interface RequestOptions {
  /** Low-priority work: it is not a user action, so other background work does not wait for it. */
  background?: boolean;
}

export class JsonRpcClient implements Disposable {
  private nextId = 0;
  private stopped = false;
  private readonly pending = new Map<number, Pending>();
  private foreground = 0;
  private readonly idlers = new Set<() => void>();
  private readonly notifications = new Map<
    string,
    Set<(params: unknown) => void>
  >();
  constructor(private readonly write: (line: string) => void) {}
  request<Result>(
    method: string,
    params: unknown = {},
    timeoutMs = 30000,
    options: RequestOptions = {},
  ): Promise<Result> {
    if (this.stopped) return Promise.reject(new RpcError(-1, "server stopped"));
    const requestId = ++this.nextId;
    return new Promise<Result>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.forget(requestId);
        try {
          this.write(serialize({ jsonrpc: "2.0", method: "$/cancelRequest", params: { id: requestId } }) + "\n");
        } catch { /* The timeout remains the relevant error if the transport is closed. */ }
        reject(new RpcError(-1, `request timed out: ${method}`));
      }, timeoutMs);
      const background = options.background === true;
      this.pending.set(requestId, {
        resolve: (value) => resolve(value as Result),
        reject,
        timer,
        background,
      });
      if (!background) this.foreground++;
      try {
        this.write(
          serialize({ jsonrpc: "2.0", id: requestId, method, params }) +
            "\n",
        );
      } catch (error) {
        clearTimeout(timer);
        this.forget(requestId);
        reject(error);
      }
    });
  }
  /** Requests a user action is still waiting for (anything not sent as background work). */
  get foregroundPending(): number {
    return this.foreground;
  }
  /** Wait until no user-action request is pending, at most `maxMs`; resolves with the time waited. */
  foregroundIdle(maxMs: number): Promise<number> {
    if (this.foreground === 0) return Promise.resolve(0);
    const started = Date.now();
    return new Promise<number>((resolve) => {
      const done = (): void => {
        clearTimeout(timer);
        this.idlers.delete(done);
        resolve(Date.now() - started);
      };
      const timer = setTimeout(done, maxMs);
      this.idlers.add(done);
    });
  }
  private forget(requestId: number): Pending | undefined {
    const pending = this.pending.get(requestId);
    if (!pending) return undefined;
    this.pending.delete(requestId);
    if (!pending.background && --this.foreground === 0)
      for (const done of [...this.idlers]) done();
    return pending;
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
      const pending = this.forget(response.id);
      if (!pending) return;
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
    this.foreground = 0;
    for (const done of [...this.idlers]) done();
    this.notifications.clear();
  }
}
