/* 迭代2 前端纯函数测试：MessageList 分段（过程聚合）+ 检索产物命中合并。 */
import { describe, expect, it } from "vitest";
import { segmentItems } from "@/components/chat/MessageList";
import {
  mergeArtifactHits,
  searchHitPath,
  type ArtifactRow,
  type SearchHit,
} from "@/components/layout/workspaceSearchModel";
import type { ChatItem } from "@/lib/types";

function user(text: string): ChatItem {
  return { kind: "user", text, t: 1 };
}
function text(text: string): ChatItem {
  return { kind: "text", text, t: 2 };
}
function thought(text: string): ChatItem {
  return { kind: "text", text, t: 3, channel: "thought" };
}
function tool(ref: string): ChatItem {
  return { kind: "tool", ref, t: 4 };
}

describe("segmentItems（查看过程 N 项）", () => {
  it("按用户消息切段；工具卡与思考块归入过程区", () => {
    const items = [
      user("问题一"),
      thought("想"),
      tool("c1"),
      text("回答一"),
      user("问题二"),
      text("回答二"),
    ];
    const segs = segmentItems(items);
    expect(segs).toHaveLength(2);
    expect(segs[0]!.user?.idx).toBe(0);
    expect(segs[0]!.process).toHaveLength(2); // thought + tool
    expect(segs[0]!.texts.map((t) => t.item.text)).toEqual(["回答一"]);
    expect(segs[1]!.process).toHaveLength(0);
    expect(segs[1]!.texts.map((t) => t.item.text)).toEqual(["回答二"]);
  });

  it("首个回复前无用户消息：独立成段且 user 为 null", () => {
    const segs = segmentItems([tool("c0"), text("开场")]);
    expect(segs).toHaveLength(1);
    expect(segs[0]!.user).toBeNull();
    expect(segs[0]!.process).toHaveLength(1);
  });

  it("空输入返回空段", () => {
    expect(segmentItems([])).toEqual([]);
  });

  it("连续用户消息各自成段", () => {
    const segs = segmentItems([user("a"), user("b")]);
    expect(segs).toHaveLength(2);
    expect(segs[0]!.texts).toHaveLength(0);
    expect(segs[1]!.user?.idx).toBe(1);
  });
});

describe("mergeArtifactHits（产物级检索）", () => {
  const base: SearchHit[] = [
    { kind: "task", id: "t1", title: "任务一" },
  ];
  const rows: ArtifactRow[] = [
    { session_id: "s1", path: "artifacts/能耗分析.docx", name: "能耗分析.docx", ext: ".docx", size: 1024 },
    { session_id: "s2", path: "figures/f1.png", name: "f1.png", ext: ".png", size: 2048 },
  ];

  it("产物行转命中并置前，携带所属会话", () => {
    const merged = mergeArtifactHits(base, rows);
    expect(merged).toHaveLength(3);
    expect(merged[0]!.kind).toBe("artifact_file");
    expect(merged[0]!.sessionId).toBe("s1");
    expect(merged[0]!.title).toBe("能耗分析.docx");
    expect(merged[2]!.kind).toBe("task");
  });

  it("去重与上限", () => {
    // 同一产物行重复出现：去重后只保留一条
    const dupRow: ArtifactRow = { session_id: "s1", path: "artifacts/能耗分析.docx", name: "能耗分析.docx", ext: ".docx", size: 1024 };
    const merged = mergeArtifactHits([], [dupRow, { ...dupRow }, { session_id: "s2", path: "figures/f1.png", name: "f1.png", ext: ".png", size: 2048 }]);
    expect(merged.filter((h) => h.id.includes("s1/artifacts"))).toHaveLength(1);
    const capped = mergeArtifactHits([], [
      { session_id: "s", path: "a", name: "a", ext: "", size: 0 },
      { session_id: "s", path: "b", name: "b", ext: "", size: 0 },
      { session_id: "s", path: "c", name: "c", ext: "", size: 0 },
    ], 2);
    expect(capped).toHaveLength(2); // cap 生效
  });

  it("产物文件深链直达所属会话", () => {
    const sid = "20260828_100000_能耗_abc123";
    const hit: SearchHit = { kind: "artifact_file", id: "x", sessionId: sid };
    expect(searchHitPath(hit)).toBe(`/chat/${encodeURIComponent(sid)}`);
    expect(searchHitPath(hit).startsWith("/chat/")).toBe(true);
  });
});
