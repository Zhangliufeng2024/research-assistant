/* R17 思考链分级单测：channel 归约（thought/plan 不与正文合并）、
 * error traceback 透传、Scheduler 间隔人性化描述。 */
import { describe, expect, it } from "vitest";
import { emptyChat, reduceChat } from "@/lib/protocolChat";
import { describeInterval } from "@/views/SchedulerView";

describe("reduceChat · channel 分级", () => {
  it("thought channel 增量进独立气泡，不并入正文", () => {
    let st = emptyChat();
    st = reduceChat(st, { type: "text", delta: "正文一" });
    st = reduceChat(st, { type: "text", delta: "想一", channel: "thought" });
    st = reduceChat(st, { type: "text", delta: "想二", channel: "thought" });
    st = reduceChat(st, { type: "text", delta: "正文二" });
    const texts = st.items.filter((i) => i.kind === "text");
    expect(texts).toHaveLength(3);
    expect(texts[0]).toMatchObject({ text: "正文一" });
    expect((texts[0] as { channel?: string }).channel).toBeUndefined();
    expect(texts[1]).toMatchObject({ text: "想一想二", channel: "thought" });
    expect(texts[2]).toMatchObject({ text: "正文二" });
    expect((texts[2] as { channel?: string }).channel).toBeUndefined();
  });

  it("plan channel 与 thought channel 互不合并", () => {
    let st = emptyChat();
    st = reduceChat(st, { type: "text", delta: "想", channel: "thought" });
    st = reduceChat(st, { type: "text", delta: "划", channel: "plan" });
    const texts = st.items.filter((i) => i.kind === "text");
    expect(texts).toHaveLength(2);
    expect(texts[0]).toMatchObject({ channel: "thought" });
    expect(texts[1]).toMatchObject({ channel: "plan" });
  });

  it("无 channel 的旧帧行为不变（向后兼容）", () => {
    let st = emptyChat();
    st = reduceChat(st, { type: "text", delta: "a" });
    st = reduceChat(st, { type: "text", delta: "b" });
    const texts = st.items.filter((i) => i.kind === "text");
    expect(texts).toHaveLength(1);
    expect(texts[0]!.text).toBe("ab");
  });

  it("error 帧 traceback 透传，新回合清除", () => {
    let st = emptyChat();
    st = reduceChat(st, {
      type: "error",
      message: "炸了",
      traceback: "Traceback...",
    });
    expect(st.error).toBe("炸了");
    expect(st.errorTrace).toBe("Traceback...");
    st = reduceChat(st, { type: "error", message: "无堆栈错误" });
    expect(st.errorTrace).toBeNull();
  });

  it("result 帧照常清除 plan/approval（channel 不干扰收尾）", () => {
    let st = emptyChat();
    st = reduceChat(st, { type: "text", delta: "想", channel: "thought" });
    st = reduceChat(st, { type: "result", stop_reason: "completed", turns: 1 });
    expect(st.phase).toBe("done");
  });
});

describe("describeInterval", () => {
  it("秒/分钟/小时/天的人性化描述", () => {
    expect(describeInterval(60)).toBe("每 60 秒");
    expect(describeInterval(600)).toBe("每 10 分钟");
    expect(describeInterval(3600)).toBe("每 1 小时");
    expect(describeInterval(7200)).toBe("每 2 小时");
    expect(describeInterval(86400)).toBe("每 1 天");
    expect(describeInterval(5400)).toBe("每 1.5 小时");
  });
});
