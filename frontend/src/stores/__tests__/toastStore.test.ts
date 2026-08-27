/* toastStore（R14-T）：入列/自动消失/上限挤出/手动关闭/便捷单例。
 * node 环境无 DOM，Toaster 组件渲染不在本文件范围（项目无 @testing-library）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast, useToastStore } from "@/stores/toastStore";

describe("toastStore（R14-T）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useToastStore.setState({ toasts: [] });
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("push 返回唯一 id；info/success 默认 4s 自动消失", () => {
    const id1 = useToastStore.getState().push({ message: "第一条" });
    // error 默认 8s：留作「info 消失后仍在屏」的对照组
    const id2 = useToastStore.getState().push({ kind: "error", message: "第二条" });
    expect(id1).not.toBe(id2);

    let toasts = useToastStore.getState().toasts;
    expect(toasts.map((t) => t.kind)).toEqual(["info", "error"]);
    expect(toasts[0]!.duration).toBe(4000);

    vi.advanceTimersByTime(3999);
    toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(2);

    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts.map((t) => t.id)).toEqual([id2]);
  });

  it("error 默认 8s：4s 时仍在，8s 时消失", () => {
    const id = useToastStore.getState().push({ kind: "error", message: "出错了" });

    vi.advanceTimersByTime(4000);
    expect(useToastStore.getState().toasts.map((t) => t.id)).toEqual([id]);

    vi.advanceTimersByTime(4000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("自定义 duration 覆盖默认值", () => {
    const id = useToastStore.getState().push({ message: "自定义", duration: 500 });
    vi.advanceTimersByTime(500);
    expect(useToastStore.getState().toasts.map((t) => t.id)).not.toContain(id);
  });

  it("栈上限 5 条：第 6 条挤掉最旧的一条", () => {
    for (let i = 1; i <= 5; i++) {
      useToastStore.getState().push({ message: `第${i}条`, duration: 60_000 });
    }
    const newestId = useToastStore.getState().push({
      kind: "error",
      message: "第6条",
      duration: 60_000,
    });

    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(5);
    expect(toasts[0]!.message).toBe("第2条"); // 最旧的「第1条」被挤出
    expect(toasts.at(-1)!.id).toBe(newestId);
  });

  it("dismiss 手动关闭并取消定时器：之后推进时间不报错、不复活", () => {
    const id = useToastStore.getState().push({ message: "手动关" });
    useToastStore.getState().dismiss(id);
    expect(useToastStore.getState().toasts).toHaveLength(0);

    vi.advanceTimersByTime(60_000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("dismiss 幂等：未知 id 无操作", () => {
    useToastStore.getState().push({ message: "在屏" });
    const before = useToastStore.getState().toasts;
    useToastStore.getState().dismiss("t-不存在");
    expect(useToastStore.getState().toasts).toBe(before); // 引用未变 → 不触发订阅者
  });

  it("便捷单例 toast.success/error/info 路由到同一 store", () => {
    toast.info("信息");
    toast.success("成功");
    toast.error("失败");
    const toasts = useToastStore.getState().toasts;
    expect(toasts.map((t) => t.kind)).toEqual(["info", "success", "error"]);
    expect(toasts.find((t) => t.kind === "error")!.duration).toBe(8000);

    const id = toast.error("带时长的错误", 1000);
    vi.advanceTimersByTime(1000);
    expect(useToastStore.getState().toasts.some((t) => t.id === id)).toBe(false);
  });

  it("duration=Infinity 不排程自动消失（常驻，仅可手动关）", () => {
    const id = useToastStore.getState().push({ message: "常驻", duration: Infinity });
    vi.advanceTimersByTime(60_000);
    expect(useToastStore.getState().toasts.map((t) => t.id)).toEqual([id]);
  });
});
