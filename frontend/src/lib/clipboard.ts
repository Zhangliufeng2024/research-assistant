/* 剪贴板写入（R14-C）：消息复制等场景用。
 *
 * navigator.clipboard 仅在安全上下文可用；桌面壳内嵌 http 页面或权限
 * 被拒时回退 textarea + execCommand（隐藏定位避免页面跳动）。全程不抛错，
 * 成功与否只看返回布尔——调用方据此决定 toast 文案。
 */
export async function copyText(text: string): Promise<boolean> {
  const nav: Navigator | undefined =
    typeof navigator !== "undefined" ? navigator : undefined;
  if (nav?.clipboard?.writeText) {
    try {
      await nav.clipboard.writeText(text);
      return true;
    } catch {
      /* 权限拒绝 / 非安全上下文 → 走回退路径 */
    }
  }
  try {
    const doc: Document | undefined =
      typeof document !== "undefined" ? document : undefined;
    if (!doc?.body) return false;
    const ta = doc.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.opacity = "0";
    doc.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try {
      ok = doc.execCommand("copy");
    } finally {
      doc.body.removeChild(ta);
    }
    return ok;
  } catch {
    return false;
  }
}
