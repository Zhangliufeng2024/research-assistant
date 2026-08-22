/* 展示格式化辅助。 */

/** 相对时间：刚刚 / n 分钟前 / n 小时前 / n 天前 / 具体日期。 */
export function formatRelative(t: number | string | undefined | null): string {
  if (t === undefined || t === null || t === "") return "";
  const ts = typeof t === "number" ? t : Date.parse(String(t));
  if (!Number.isFinite(ts)) return "";
  const diff = Date.now() - ts;
  const min = 60_000;
  if (diff < min) return "刚刚";
  if (diff < 60 * min) return `${Math.floor(diff / min)} 分钟前`;
  if (diff < 24 * 60 * min) return `${Math.floor(diff / (60 * min))} 小时前`;
  if (diff < 7 * 24 * 60 * min) return `${Math.floor(diff / (24 * 60 * min))} 天前`;
  const d = new Date(ts);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 秒 → m:ss / h:mm:ss。 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return (h > 0 ? `${h}:` : "") + `${mm}:${String(sec).padStart(2, "0")}`;
}

/** token 数缩写：1234 → 1.2k，1234567 → 1.2M。 */
export function formatTokens(n: number | undefined | null): string {
  if (!n) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/** 会话标题回退：无标题时用首条消息。 */
export function sessionTitle(title: string | null, lastMessage: string): string {
  const t = (title || "").trim();
  if (t) return t;
  const l = (lastMessage || "").trim();
  return l ? l.slice(0, 30) : "未命名会话";
}
