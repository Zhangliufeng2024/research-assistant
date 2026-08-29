/* 响应式断点 hook（阶段 4 / U-11 窄屏兜底）。
 *
 * jsdom 等无 matchMedia 的环境按「宽屏」处理（返回 true）——测试与旧浏览器
 * 下行为退化为宽屏布局，不抛错；真实浏览器正常订阅变化。
 */
import { useEffect, useState } from "react";

function compute(query: string): boolean {
  try {
    return window.matchMedia?.(query)?.matches ?? true;
  } catch {
    return true;
  }
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => compute(query));

  useEffect(() => {
    let mql: MediaQueryList;
    try {
      mql = window.matchMedia?.(query) as MediaQueryList;
    } catch {
      return;
    }
    if (!mql) return;
    const onChange = (ev: MediaQueryListEvent) => setMatches(ev.matches);
    // 现代 API（addEventListener）；旧实现退化 addListener
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    }
    if (typeof mql.addListener === "function") {
      mql.addListener(onChange);
      return () => mql.removeListener(onChange);
    }
  }, [query]);

  return matches;
}
