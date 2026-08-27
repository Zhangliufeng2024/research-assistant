/* copyText（R14-C）：clipboard API 优先、execCommand 回退、全程不抛错。
 * node 环境无真实 DOM：navigator/document 用 vi.stubGlobal 替身。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "@/lib/clipboard";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 替身 document：createElement 恒返回同一个假 textarea。 */
function stubDoc(execCommand: (...a: unknown[]) => boolean) {
  const ta = {
    value: "",
    style: {} as Record<string, string>,
    setAttribute: vi.fn(),
    select: vi.fn(),
    setSelectionRange: vi.fn(),
  };
  const doc = {
    body: { appendChild: vi.fn(), removeChild: vi.fn() },
    createElement: vi.fn(() => ta),
    execCommand: vi.fn(execCommand),
  };
  vi.stubGlobal("document", doc);
  return { doc, ta };
}

describe("copyText（R14-C）", () => {
  it("navigator.clipboard 可用：直接写入并返回 true", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await expect(copyText("你好")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("你好");
  });

  it("clipboard API 被拒：回退 textarea + execCommand，且清理挂载节点", async () => {
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    const { doc, ta } = stubDoc(() => true);

    await expect(copyText("回退路径")).resolves.toBe(true);
    expect(doc.createElement).toHaveBeenCalledWith("textarea");
    expect(ta.value).toBe("回退路径");
    expect(ta.select).toHaveBeenCalled();
    expect(ta.setSelectionRange).toHaveBeenCalledWith(0, 4);
    expect(doc.execCommand).toHaveBeenCalledWith("copy");
    expect(doc.body.appendChild).toHaveBeenCalled();
    expect(doc.body.removeChild).toHaveBeenCalledWith(ta); // finally 兜底移除
  });

  it("两条路都失败（execCommand 返回 false）→ false，不抛错", async () => {
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    stubDoc(() => false);

    await expect(copyText("x")).resolves.toBe(false);
  });

  it("execCommand 抛错同样吞掉 → false，节点仍被移除", async () => {
    vi.stubGlobal("navigator", {}); // 无 clipboard
    const { doc, ta } = stubDoc(() => {
      throw new Error("boom");
    });

    await expect(copyText("y")).resolves.toBe(false);
    expect(doc.body.removeChild).toHaveBeenCalledWith(ta);
  });

  it("既无 clipboard 也无 document（异常宿主）→ false", async () => {
    vi.stubGlobal("navigator", {});

    await expect(copyText("z")).resolves.toBe(false);
  });
});
