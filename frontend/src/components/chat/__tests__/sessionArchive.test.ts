/* Top10-C 归档持久化纯函数回归（node 环境：显式注入 localStorage 桩）。 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ARCHIVED_SESSIONS_KEY,
  archiveId,
  loadArchivedIds,
  parseArchivedIds,
  saveArchivedIds,
  unarchiveId,
  type KeyValueStorage,
} from "@/components/chat/sessionArchive";

/** Map 后备的内存存储桩；可配置抛错模拟配额/占用异常。 */
function makeStorage(opts: {
  initial?: Record<string, string>;
  failSet?: boolean;
  failGet?: boolean;
} = {}): KeyValueStorage & { dump(): Record<string, string> } {
  const map = new Map<string, string>(Object.entries(opts.initial ?? {}));
  return {
    getItem(key) {
      if (opts.failGet) throw new Error("storage unavailable");
      return map.get(key) ?? null;
    },
    setItem(key, value) {
      if (opts.failSet) throw new Error("QuotaExceededError");
      map.set(key, value);
    },
    dump() {
      return Object.fromEntries(map);
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("parseArchivedIds：脏数据规整", () => {
  it("字符串数组原样保留", () => {
    expect(parseArchivedIds(["a", "b"])).toEqual(["a", "b"]);
  });

  it("非数组返回空", () => {
    expect(parseArchivedIds(null)).toEqual([]);
    expect(parseArchivedIds("x")).toEqual([]);
    expect(parseArchivedIds({ id: "a" })).toEqual([]);
  });

  it("剔除非字符串与空串并去重保序", () => {
    expect(parseArchivedIds(["a", 1, null, "", "a", "b"])).toEqual(["a", "b"]);
  });
});

describe("loadArchivedIds / saveArchivedIds：localStorage 读写", () => {
  it("写入后可读回同一列表", () => {
    const storage = makeStorage();
    expect(saveArchivedIds(["s1", "s2"], storage)).toBe(true);
    expect(loadArchivedIds(storage)).toEqual(["s1", "s2"]);
    expect(JSON.parse(storage.dump()[ARCHIVED_SESSIONS_KEY]!)).toEqual([
      "s1",
      "s2",
    ]);
  });

  it("键缺失返回空数组", () => {
    expect(loadArchivedIds(makeStorage())).toEqual([]);
  });

  it("损坏 JSON / 脏数据自愈为空数组，不抛出", () => {
    expect(
      loadArchivedIds(
        makeStorage({ initial: { [ARCHIVED_SESSIONS_KEY]: "{broken" } }),
      ),
    ).toEqual([]);
    expect(
      loadArchivedIds(
        makeStorage({ initial: { [ARCHIVED_SESSIONS_KEY]: '"just-a-string"' } }),
      ),
    ).toEqual([]);
  });

  it("读取异常（占用/权限）静默降级为空数组", () => {
    expect(loadArchivedIds(makeStorage({ failGet: true }))).toEqual([]);
  });

  it("写入失败（配额超限）返回 false 且不抛出——调用方降级为仅内存态", () => {
    const storage = makeStorage({ failSet: true });
    expect(saveArchivedIds(["s1"], storage)).toBe(false);
  });

  it("未注入 storage 且全局不可用时不崩溃（node 环境兜底）", () => {
    const g = globalThis as { localStorage?: KeyValueStorage };
    const saved = g.localStorage;
    delete g.localStorage; // localStorage 是可选字段，可直接移除
    try {
      expect(loadArchivedIds()).toEqual([]);
      expect(saveArchivedIds(["s1"])).toBe(false);
    } finally {
      if (saved) g.localStorage = saved;
    }
  });
});

describe("archiveId / unarchiveId：幂等集合操作", () => {
  it("归档幂等且不改入参", () => {
    const base = ["a"];
    expect(archiveId(base, "b")).toEqual(["a", "b"]);
    expect(archiveId(archiveId(base, "b"), "b")).toEqual(["a", "b"]);
    expect(base).toEqual(["a"]); // 纯函数
  });

  it("取消归档幂等", () => {
    expect(unarchiveId(["a", "b"], "a")).toEqual(["b"]);
    expect(unarchiveId(["b"], "a")).toEqual(["b"]);
  });

  it("往返：归档再取消恢复原状", () => {
    expect(unarchiveId(archiveId(["x"], "y"), "y")).toEqual(["x"]);
  });
});
