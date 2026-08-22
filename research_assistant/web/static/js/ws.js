/* WebSocket 客户端（命名通道：task = /ws/generate，chat = /ws/chat）。
 *
 * 双通道并存是有意的：从运行中的任务切到会话页不应断开生成连接
 * （服务端在连接断开时会置位 cancel_event 终止生成，docs/protocol.md §5.2）。
 * 有意不做自动重连——静默重连只会造成"看起来还在跑"的假象；
 * 断开由 UI 层给出明确横幅，pipeline 任务可从运行历史一键续跑。
 *
 * 全局 S.conn 只反映 task（生成）通道；chat 通道状态由会话视图经
 * onStatus 自行管理。
 */
import { S } from "./store.js";

const PATHS = { task: "/ws/generate", chat: "/ws/chat" };
const socks = new Map(); // channel → WebSocket

function sockOf(channel) {
  return socks.get(channel || "task") || null;
}

export function wsConnected(channel = "task") {
  const s = sockOf(channel);
  return !!s && s.readyState === WebSocket.OPEN;
}

/* 发送 JSON；返回是否成功入发 */
export function wsSend(obj, channel = "task") {
  const s = sockOf(channel);
  if (!s || s.readyState !== WebSocket.OPEN) return false;
  s.send(JSON.stringify(obj));
  return true;
}

/* 关闭指定通道；不传参则全关 */
export function wsClose(channel) {
  if (channel === undefined) {
    for (const ch of [...socks.keys()]) wsClose(ch);
    return;
  }
  const s = socks.get(channel);
  if (s) {
    try { s.close(); } catch { /* ignore */ }
    socks.delete(channel);
  }
}

export function wsConnect({ channel = "task", query = "", onMessage, onStatus }) {
  wsClose(channel);
  const path = (PATHS[channel] || channel) + (query ? `?${query}` : "");
  if (channel === "task") S.set({ conn: "connecting" });
  onStatus && onStatus("connecting");

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  let opened = false;
  const sock = new WebSocket(`${proto}//${location.host}${path}`);
  socks.set(channel, sock);

  sock.onopen = () => {
    opened = true;
    if (channel === "task") S.set({ conn: "open" });
    onStatus && onStatus("open");
  };
  sock.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    onMessage && onMessage(msg);
  };
  sock.onerror = () => {
    if (channel === "task") S.set({ conn: "error" });
    onStatus && onStatus("error");
  };
  sock.onclose = () => {
    socks.delete(channel);
    if (channel === "task") S.set({ conn: "closed" });
    onStatus && onStatus(opened ? "closed" : "error");
  };
  return sock;
}
