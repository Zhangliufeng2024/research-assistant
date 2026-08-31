/* 本地 API token（P1-3）。
 *
 * 后端在进程启动时生成一个一次性随机 token，并在**响应入口 HTML 时**注入
 * 到 window（见 web/app.py 的 TokenInjectingStatic）。所有 /api 与 /ws
 * 请求必须携带它——否则同机任意脚本都能伪造 Origin 头直接调用本地端点
 * （Origin 只是个请求头，不是凭证）。
 *
 * 取值规则：
 * - 生产（webview / uvicorn）：入口 HTML 注入，页面加载即有；
 * - 开发（vite dev server 直连后端静态页）：同样由后端入口页注入；
 * - 缺失时返回空串，调用方**必须**按「未启用 token」处理（不附加头），
 *   这样裸跑后端（测试、嵌入场景）依然可用。绝不能因取不到 token 而报错。
 */

declare global {
  interface Window {
    __RA_API_TOKEN__?: string;
  }
}

/** 读取后端注入的一次性 token；未启用时为空串。 */
export function apiToken(): string {
  if (typeof window === "undefined") return "";
  return window.__RA_API_TOKEN__ || "";
}
