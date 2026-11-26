import { afterEach, describe, expect, it, vi } from "vitest";
import {
  JsonRpcClient,
  LineSplitter,
  RpcError,
} from "../../src/server/jsonrpc";

afterEach(() => vi.useRealTimers());
describe("line splitter", () => {
  it("handles partial CRLF, multiple lines and split Unicode bytes", () => {
    const lines: string[] = [];
    const splitter = new LineSplitter((line) => lines.push(line));
    splitter.push("one\r");
    splitter.push("\ntwo\n\n");
    const unicode = Buffer.from("café\n");
    splitter.push(unicode.subarray(0, 4));
    splitter.push(unicode.subarray(4));
    splitter.push("tail");
    splitter.end();
    expect(lines).toEqual(["one", "two", "café", "tail"]);
  });
});
describe("JSON-RPC client", () => {
  it("matches out-of-order responses and preserves RPC errors", async () => {
    const write = vi.fn();
    const client = new JsonRpcClient(write);
    const first = client.request("first");
    const second = client.request("second");
    const failure = expect(first).rejects.toMatchObject({
      code: -32002,
      message: "absent",
      data: { detail: 1 },
    });
    client.handleLine(
      JSON.stringify({ jsonrpc: "2.0", id: 2, result: "second" }),
    );
    client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        error: { code: -32002, message: "absent", data: { detail: 1 } },
      }),
    );
    await expect(second).resolves.toBe("second");
    await failure;
    expect(JSON.parse(write.mock.calls[0][0])).toEqual({
      jsonrpc: "2.0",
      id: 1,
      method: "first",
      params: {},
    });
    client.dispose();
  });
  it("times out and rejects pending and future requests on dispose", async () => {
    vi.useFakeTimers();
    const write = vi.fn();
    const client = new JsonRpcClient(write);
    const timed = expect(client.request("slow", {}, 10)).rejects.toMatchObject({
      code: -1,
    });
    await vi.advanceTimersByTimeAsync(10);
    await timed;
    expect(JSON.parse(write.mock.calls[1][0])).toEqual({
      jsonrpc: "2.0", method: "$/cancelRequest", params: { id: 1 },
    });
    const pending = expect(client.request("pending")).rejects.toThrow(
      "server stopped",
    );
    client.dispose();
    await pending;
    await expect(client.request("after")).rejects.toThrow("server stopped");
    expect(vi.getTimerCount()).toBe(0);
  });
  it("delivers notifications with isolated callbacks and removable listeners", () => {
    const client = new JsonRpcClient(() => {});
    client.onNotification("hover", () => {
      throw new Error("bad listener");
    });
    const listener = vi.fn();
    const registration = client.onNotification("hover", listener);
    client.handleLine('{"jsonrpc":"2.0","method":"hover","params":{"node":1}}');
    expect(listener).toHaveBeenCalledWith({ node: 1 });
    registration.dispose();
    client.handleLine('{"jsonrpc":"2.0","method":"hover","params":{}}');
    expect(listener).toHaveBeenCalledOnce();
    client.handleLine("bad JSON");
    client.handleLine("[]");
    client.dispose();
  });
  it("cleans up synchronous write errors and malformed replies", async () => {
    const broken = new JsonRpcClient(() => {
      throw new Error("closed pipe");
    });
    await expect(broken.request("test")).rejects.toThrow("closed pipe");
    broken.dispose();
    const client = new JsonRpcClient(() => {});
    const result = expect(client.request("test")).rejects.toBeInstanceOf(
      RpcError,
    );
    client.handleLine('{"jsonrpc":"2.0","id":1}');
    await result;
    client.dispose();
  });
});
describe("background requests", () => {
  const answer = (client: JsonRpcClient, id: number) =>
    client.handleLine(JSON.stringify({ jsonrpc: "2.0", id, result: id }));
  it("only user-action requests keep the client busy", async () => {
    const client = new JsonRpcClient(() => {});
    const background = client.request("inspect.managed.spyRead", {}, 1000, { background: true });
    expect(client.foregroundPending).toBe(0);
    await expect(client.foregroundIdle(1000)).resolves.toBe(0);
    const action = client.request("spy.start");
    expect(client.foregroundPending).toBe(1);
    const idle = vi.fn();
    void client.foregroundIdle(5000).then(idle);
    await Promise.resolve();
    expect(idle).not.toHaveBeenCalled();
    answer(client, 2);
    await action;
    await vi.waitFor(() => expect(idle).toHaveBeenCalledOnce());
    expect(client.foregroundPending).toBe(0);
    answer(client, 1);
    await background;
    client.dispose();
  });
  it("stops waiting after the limit, for a request that never answers", async () => {
    vi.useFakeTimers();
    const client = new JsonRpcClient(() => {});
    const action = expect(client.request("inspect.coverage", {}, 30_000)).rejects.toThrow("request timed out");
    const idle = vi.fn();
    void client.foregroundIdle(2000).then(idle);
    await vi.advanceTimersByTimeAsync(1999);
    expect(idle).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2);
    expect(idle).toHaveBeenCalledWith(2000);
    await vi.advanceTimersByTimeAsync(30_000);
    await action;
    expect(client.foregroundPending).toBe(0);
    client.dispose();
  });
  it("releases waiters when a request times out, fails to write or the client is disposed", async () => {
    vi.useFakeTimers();
    const client = new JsonRpcClient(() => {});
    const slow = expect(client.request("a", {}, 100)).rejects.toThrow("timed out");
    const idle = vi.fn();
    void client.foregroundIdle(60_000).then(idle);
    await vi.advanceTimersByTimeAsync(101);
    await slow;
    expect(idle).toHaveBeenCalledOnce();
    const open = expect(client.request("b")).rejects.toThrow("server stopped");
    const waiting = vi.fn();
    void client.foregroundIdle(60_000).then(waiting);
    client.dispose();
    await open;
    await vi.advanceTimersByTimeAsync(0);
    expect(waiting).toHaveBeenCalledOnce();
  });
});
