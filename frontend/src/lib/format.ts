/* 展示格式化辅助。 */

/** 时间戳归一为毫秒。后端契约是 epoch 秒（protocol.md：time.time()/st_mtime），
 * 而前端 Date 体系用毫秒——§6.3 的「1月22日」即秒值被当毫秒、diff 变 56 年
 * 落进绝对日期分支渲染出 1970 年所致。毫秒值自 1973-03 起恒 ≥ 1e11，
 * 以此区分两种单位（秒值到 5138 年都不会误判）。 */
function toMillis(t: number | string): number {
  const v = typeof t === "number" ? t : Date.parse(t);
  return v >= 0 && v < 1e11 ? v * 1000 : v;
}

/** 相对时间：刚刚 / n 分钟前 / n 小时前 / n 天前 / 具体日期。 */
export function formatRelative(t: number | string | undefined | null): string {
  if (t === undefined || t === null || t === "") return "";
  const ts = toMillis(typeof t === "number" ? t : String(t));
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
