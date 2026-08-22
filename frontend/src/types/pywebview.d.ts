/**
 * pywebview 注入对象的环境声明（桌面壳 js_api 桥，见 desktop.py DesktopBridge）。
 * 浏览器直连等非桌面环境下 `window.pywebview` 为 undefined —— 所有访问点
 * 都必须先探测再调用（WorkspaceModal 的 nativeOk 探测逻辑）。
 */

interface PywebviewApi {
  /** 原生选夹对话框；取消返回空串。 */
  select_folder(title?: string): Promise<string>;
  /** 连通性探测：返回 "ok"。 */
  ping(): Promise<string>;
}

interface Window {
  pywebview?: {
    api?: PywebviewApi;
  };
}
