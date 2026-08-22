/* 轻量响应式 store：subscribe/emit，~40 行，零依赖 */

export function createStore(initial = {}) {
  const state = { ...initial };
  const subs = new Set();
  return {
    get: (k) => state[k],
    get all() { return state; },
    /* set(patch)：对象或 (state)=>patch 函数；通知所有订阅者 */
    set(patch) {
      Object.assign(state, typeof patch === "function" ? patch(state) : patch);
      for (const fn of subs) {
        try { fn(state); } catch (e) { console.error("[store]", e); }
      }
    },
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

/* 全局单例 store —— 各视图共享 */
export const S = createStore({
  route: "task",
  status: null,          // /api/status 响应
  conn: "idle",          // idle | connecting | open | closed | error
  running: false,        // 本连接是否有任务在跑
  task: null,            // 协议归约后的任务态（protocol.emptyTask）
  runs: [],              // GET /api/runs
  papers: [],
  paperDetail: null,
});
