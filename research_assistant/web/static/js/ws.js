/* WebSocket 客户端（生成通道）。
 *
 * 有意不做自动重连：服务端在连接断开时会置位 cancel_event 终止生成
 * （docs/protocol.md §5.2），静默重连只会造成"看起来还在跑"的假象。
 * 断开由 UI 层给出明确横幅，pipeline 任务可从运行历史一键续跑。
 */
import { S } from "./store.js";

let sock = null;

export function wsConnected() {
  return sock && sock.readyState === WebSocket.OPEN;
}

/* 发送 JSON；返回是否成功入发 */
export function wsSend(obj) {
  if (!wsConnected()) return false;
  sock.send(JSON.stringify(obj));
  return true;
}

export function wsClose() {
  if (sock) { try { sock.close(); } catch { /* ignore */ } sock = null; }
}

export function wsConnect({ onMessage, onStatus }) {
  wsClose();
  S.set({ conn: "connecting" });
  onStatus && onStatus("connecting");
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  sock = new WebSocket(`${proto}//${location.host}/ws/generate`);

  sock.onopen = () => { S.set({ conn: "open" }); onStatus && onStatus("open"); };
  sock.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    onMessage && onMessage(msg);
  };
  sock.onerror = () => { S.set({ conn: "error" }); onStatus && onStatus("error"); };
  sock.onclose = () => {
    const wasOpen = S.get("conn") === "open";
    sock = null;
    S.set({ conn: "closed" });
    onStatus && onStatus(wasOpen ? "closed" : "error");
  };
  return sock;
}
