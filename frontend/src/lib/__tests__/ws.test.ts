/* R10 回归：ws.ts 的 socket 登记表。
 *
 * 背景（用户在另一台电脑「永久思考中」/「无法建立与服务端的连接」）：
 * R7 重写时 wsConnect 创建 socket 后从未写入 socks 表——wsSend/wsConnected
 * 永远失败，会话与任务的所有帧（首条消息、steer、审批、停止）都发不出，
 * 而服务端握手正常。此前的测试全部逃逸：reducer 测试不碰 ws 层，
 * 后端 E2E 用裸 websocket 客户端直连。这里用假 WebSocket 把登记行为锁死。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { wsClose, wsConnect, wsConnected, wsSend } from "@/lib/ws";

type Handler = ((ev?: unknown) => void) | null;

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static OPEN_CONST = FakeWebSocket.OPEN; // 与浏览器常量对齐
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: Handler = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: Handler = null;
  onclose: Handler = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    if (this.readyState !== FakeWebSocket.OPEN) {
      throw new Error("FakeWebSocket: not open");
    }
    this.sent.push(data);
  }

  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  /** 测试辅助：模拟握手完成。 */
  simulateOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** 测试辅助：模拟服务端推帧。 */
  simulateMessage(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

describe("ws.ts socket 登记（R10 回归）", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("location", { protocol: "http:", host: "127.0.0.1:50000" });
    FakeWebSocket.instances = [];
  });
  afterEach(() => {
    wsClose();
    vi.unstubAllGlobals();
  });

  it("连接打开后 wsSend 可送达帧、wsConnected 为真（缺失登记即本测试失败）", () => {
    wsConnect({ channel: "chat", query: "session=s1" });
    const sock = FakeWebSocket.instances.at(-1)!;
    // 握手完成前：未开
    expect(wsConnected("chat")).toBe(false);
    sock.simulateOpen();

    expect(wsConnected("chat")).toBe(true);
    const ok = wsSend({ action: "user", text: "你好" }, "chat");
    expect(ok).toBe(true);
    expect(sock.sent).toEqual([JSON.stringify({ action: "user", text: "你好" })]);
  });

  it("URL 拼装：通道路径 + 查询串（/ws/chat 为后端裸挂的兼容路径）", () => {
    wsConnect({ channel: "chat", query: "session=abc" });
    expect(FakeWebSocket.instances.at(-1)!.url).toBe(
      "ws://127.0.0.1:50000/ws/chat?session=abc",
    );
    wsConnect({ channel: "task" });
    expect(FakeWebSocket.instances.at(-1)!.url).toBe("ws://127.0.0.1:50000/ws/generate");
  });

  it("服务端帧路由到 onMessage 且按 JSON 解析", () => {
    const seen: unknown[] = [];
    wsConnect({ channel: "task", onMessage: (m) => seen.push(m) });
    FakeWebSocket.instances.at(-1)!.simulateOpen();
    FakeWebSocket.instances.at(-1)!.simulateMessage({ type: "connected" });
    expect(seen).toEqual([{ type: "connected" }]);
  });

  it("重连竞态：旧 socket 迟到的 onclose 不误删新连接", () => {
    wsConnect({ channel: "chat" });
    const oldSock = FakeWebSocket.instances.at(-1)!;
    oldSock.simulateOpen();

    wsConnect({ channel: "chat" }); // 重连：内部先关旧连再建新连
    const newSock = FakeWebSocket.instances.at(-1)!;
    newSock.simulateOpen();

    // 旧 socket 此刻才触发 onclose（迟到事件）：不得清掉新连接的登记
    oldSock.readyState = FakeWebSocket.OPEN;
    oldSock.onclose?.();

    expect(wsConnected("chat")).toBe(true);
    expect(wsSend({ action: "stop" }, "chat")).toBe(true);
    expect(newSock.sent.length).toBe(1);
  });

  it("断开后状态如实：登记清除、wsSend 失败", () => {
    const statuses: string[] = [];
    wsConnect({ channel: "chat", onStatus: (s) => statuses.push(s) });
    const sock = FakeWebSocket.instances.at(-1)!;
    sock.simulateOpen();
    sock.close(); // 已 opened → "closed"
    expect(statuses).toEqual(["connecting", "open", "closed"]);
    expect(wsConnected("chat")).toBe(false);
    expect(wsSend({}, "chat")).toBe(false);
  });

  it("未 open 即断：状态报 error（而非 closed）", () => {
    const statuses: string[] = [];
    wsConnect({ channel: "chat", onStatus: (s) => statuses.push(s) });
    FakeWebSocket.instances.at(-1)!.close();
    expect(statuses).toEqual(["connecting", "error"]);
  });
});
