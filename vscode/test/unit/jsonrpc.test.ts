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
    const client = new JsonRpcClient(() => {});
    const timed = expect(client.request("slow", {}, 10)).rejects.toMatchObject({
      code: -1,
    });
    await vi.advanceTimersByTimeAsync(10);
    await timed;
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
