/* REST 封装：超时 + 错误归一 */

async function request(url, opts = {}, timeoutMs = 15000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json())?.detail || ""; } catch { /* ignore */ }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: (url) => request(url),
  post: (url, body) => request(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }),
  del: (url) => request(url, { method: "DELETE" }),
};
