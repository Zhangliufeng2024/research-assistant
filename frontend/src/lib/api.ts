/* REST 封装：超时 + 错误归一（移植自旧前端 api.js）。
 *
 * P1-3：所有请求自动附带本地 API token（后端在入口 HTML 注入到 window）。
 * token 缺失时不附加头——裸跑后端（测试/嵌入）不启用 token，行为不变。
 * 用 Headers 合并而不是展开对象：upload 不能手设 Content-Type（边界由
 * 浏览器生成），合并方式必须保留这一特性。
 */
import { apiToken } from "./apiToken";

async function request<T>(
  url: string,
  opts: RequestInit = {},
  timeoutMs = 15000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const headers = new Headers(opts.headers);
  const token = apiToken();
  if (token) headers.set("X-RA-Token", token);
  try {
    const res = await fetch(url, { ...opts, headers, signal: ctrl.signal });
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
  /** timeoutMs 可选：默认 15s 不足以覆盖较慢的一次性生成（如提示词增强
   * 后端 45s），调用方按需放宽；与 upload 的尾部可选超时同风格。 */
  post: <T>(url: string, body?: unknown, timeoutMs?: number) =>
    request<T>(
      url,
      {
        method: "POST",
        headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      },
      timeoutMs,
    ),
  put: <T>(url: string, body?: unknown) =>
    request<T>(url, {
      method: "PUT",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(url: string, body?: unknown) =>
    request<T>(url, {
      method: "PATCH",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  del: <T>(url: string) => request<T>(url, { method: "DELETE" }),
  /** multipart 上传（R16 附件）：不可手设 Content-Type——边界由浏览器生成。
   * 超时放宽：附件可能远大于 JSON 负载。 */
  upload: <T>(url: string, form: FormData, timeoutMs = 120_000) =>
    request<T>(url, { method: "POST", body: form }, timeoutMs),
};
