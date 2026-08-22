/* WebSocket 客户端（命名通道：task = /ws/generate，chat = /ws/chat）。
 *
 * 双通道并存是有意的：从运行中的任务切到会话页不应断开生成连接
 * （服务端在连接断开时会置位 cancel_event 终止生成，docs/protocol.md §5.2）。
 * 有意不做自动重连——静默重连只会造成「看起来还在跑」的假象；
 * 断开由 UI 层给出明确横幅，pipeline 任务可从运行历史一键续跑。
 * （移植自旧前端 ws.js；socket 登记表为模块级，路由切换不断连。）
 */
import type { ConnStatus, ServerFrame, WsChannel } from "./types";

const PATHS: Record<WsChannel, string> = { task: "/ws/generate", chat: "/ws/chat" };

const socks = new Map<WsChannel, WebSocket>();

export function wsConnected(channel: WsChannel = "task"): boolean {
  const s = socks.get(channel);
  return !!s && s.readyState === WebSocket.OPEN;
}

/** 发送 JSON；返回是否成功入发。 */
export function wsSend(obj: unknown, channel: WsChannel = "task"): boolean {
  const s = socks.get(channel);
  if (!s || s.readyState !== WebSocket.OPEN) return false;
  s.send(JSON.stringify(obj));
  return true;
}

/** 关闭指定通道；不传参则全关。 */
export function wsClose(channel?: WsChannel): void {
  if (channel === undefined) {
    for (const ch of [...socks.keys()]) wsClose(ch);
    return;
  }
  const s = socks.get(channel);
  if (s) {
    try {
      s.close();
    } catch {
      /* ignore */
    }
    socks.delete(channel);
  }
}

export function wsConnect({
  channel = "task",
  query = "",
  onMessage,
  onStatus,
}: {
  channel?: WsChannel;
  query?: string;
  onMessage?: (msg: ServerFrame) => void;
  onStatus?: (status: ConnStatus) => void;
}): WebSocket {
  wsClose(channel);
  const path = (PATHS[channel] ?? channel) + (query ? `?${query}` : "");
  onStatus?.("connecting");

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  let opened = false;
  const sock = new WebSocket(`${proto}//${location.host}${path}`);

  sock.onopen = () => {
    opened = true;
    onStatus?.("open");
  };
  sock.onmessage = (ev) => {
    let msg: ServerFrame;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    onMessage?.(msg);
  };
  sock.onerror = () => {
    onStatus?.("error");
  };
  sock.onclose = () => {
    socks.delete(channel);
    onStatus?.(opened ? "closed" : "error");
  };
  return sock;
}
