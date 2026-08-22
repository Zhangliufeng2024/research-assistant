/* REST 封装：超时 + 错误归一（移植自旧前端 api.js）。 */

async function request<T>(
  url: string,
  opts: RequestInit = {},
  timeoutMs = 15000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    if (!res.ok) {
      let detail = "";
      try {
        detail = ((await res.json()) as { detail?: string })?.detail || "";
      } catch {
        /* 非 JSON 错误体 */
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const ct = res.headers.get("content-type") || "";
    return (ct.includes("application/json")
      ? await res.json()
      : await res.text()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: <T>(url: string) => request<T>(url),
  post: <T>(url: string, body?: unknown) =>
    request<T>(url, {
      method: "POST",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  del: <T>(url: string) => request<T>(url, { method: "DELETE" }),
};
