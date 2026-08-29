/* 每会话持久状态（阶段 4 / U-4 常驻会话区的状态层）。
 *
 * 设计文档 §2：切换会话 = 切换会话状态，组件树不重挂；输入草稿与滚动
 * 锚点按会话 id 键存取，离开会话时自动持久化到 localStorage（崩溃恢复可用）。
 *
 * 语义：
 * - 草稿：Composer 受控值的外部镜像。组件树常驻后 Composer 不再因切会话
 *   重挂，靠「draftKey 变化 → 从本 store 恢复」实现每会话草稿隔离。
 *   未发送的新会话（sessionId=null）用 NEW_DRAFT_KEY 兜底键。
 * - 滚动锚点：切走会话时记录消息流 scrollTop，重进时尽力恢复（仅当用户
 *   曾向上翻阅——贴底跟随态没有锚定价值，恢复跟随即可）。
 *
 * localStorage 故障（隐私模式等）全部静默：内存态仍然可用。
 */
import { create } from "zustand";

const STORAGE_KEY = "ra.session-state.v1";

/** 未发送新会话的草稿键（sessionId 尚不存在时的兜底标识）。 */
export const NEW_DRAFT_KEY = "__new__";

interface PersistedState {
  drafts: Record<string, string>;
  anchors: Record<string, number>;
}

function loadPersisted(): PersistedState {
  try {
    if (typeof localStorage === "undefined") return { drafts: {}, anchors: {} };
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { drafts: {}, anchors: {} };
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      drafts: typeof parsed.drafts === "object" && parsed.drafts ? parsed.drafts : {},
      anchors: typeof parsed.anchors === "object" && parsed.anchors ? parsed.anchors : {},
    };
  } catch {
    return { drafts: {}, anchors: {} };
  }
}

function persist(state: PersistedState): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* 隐私模式/配额满：放弃持久化，内存态不受影响 */
  }
}

interface SessionStore {
  /** 输入草稿（按会话 id；新会话用 NEW_DRAFT_KEY）。 */
  drafts: Record<string, string>;
  /** 滚动锚点（按会话 id，px）。 */
  anchors: Record<string, number>;
  getDraft(key: string | null): string;
  setDraft(key: string | null, value: string): void;
  /** 发送成功/会话删除后清除草稿。 */
  clearDraft(key: string | null): void;
  getAnchor(key: string | null): number;
  setAnchor(key: string | null, top: number): void;
  clearSession(key: string): void;
}

const keyOf = (key: string | null): string => key ?? NEW_DRAFT_KEY;

export const useSessionStore = create<SessionStore>()((set, get) => {
  const initial = loadPersisted();
  return {
    drafts: initial.drafts,
    anchors: initial.anchors,

    getDraft: (key) => get().drafts[keyOf(key)] ?? "",

    setDraft: (key, value) => {
      const k = keyOf(key);
      set((s) => {
        const prev = s.drafts[k];
        if (prev === value) return s; // 无变化不写盘
        const drafts = { ...s.drafts, [k]: value };
        persist({ drafts, anchors: s.anchors });
        return { drafts };
      });
    },

    clearDraft: (key) => {
      const k = keyOf(key);
      set((s) => {
        if (!(k in s.drafts)) return s;
        const drafts = { ...s.drafts };
        delete drafts[k];
        persist({ drafts, anchors: s.anchors });
        return { drafts };
      });
    },

    getAnchor: (key) => get().anchors[keyOf(key)] ?? 0,

    setAnchor: (key, top) => {
      const k = keyOf(key);
      set((s) => {
        const prev = s.anchors[k];
        if (prev === top) return s;
        const anchors = { ...s.anchors, [k]: top };
        persist({ drafts: s.drafts, anchors });
        return { anchors };
      });
    },

    clearSession: (key) => {
      set((s) => {
        const k = keyOf(key);
        const drafts = { ...s.drafts };
        const anchors = { ...s.anchors };
        delete drafts[k];
        delete anchors[k];
        persist({ drafts, anchors });
        return { drafts, anchors };
      });
    },
  };
});
