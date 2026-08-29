// @vitest-environment jsdom
/* 项目总览的数据加载 effect（A+ 1.2）。
 *
 * 缺陷：useEffect 依赖数组里放了 `home?.project`——而 `home` 来自
 * `api.get(...).then(setHome)`，**每次请求都是全新对象**，引用必变。
 * 于是形成 refresh → setHome(新对象) → effect 重跑 → refresh ……
 * 落地页会以网络速度无限轮询 `/api/project/home`。
 *
 * 隐蔽之处：响应内容不变，界面看起来完全正常，只有 Network 面板能看出
 * 异常——这也是它能长期存活的原因。
 *
 * 本文件核心断言是「**恰好 1 次**」，这是该缺陷唯一的机检信号。 */
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectHomeView } from "@/views/ProjectHomeView";
import { renderWithRouter } from "@/test/domTestUtils";

const HOME = {
  project: { id: "p1", name: "测试项目", root: "D:/ws/proj", instructions: "" },
  overview: { counts: {}, uncovered_claims: 0 },
  quality: {
    ready_for_synthesis: true,
    failed_runs: 0,
    orphan_evidence: 0,
    claims: { total: 3, supported: 3, uncovered: 0 },
  },
  threads: [],
  tasks: [],
  quality_items: [],
  artifacts: [],
  decisions: [],
  usage: { summary: { cost_usd: 0.5, total_tokens: 1000, turns: 4, runs: 1, failed_runs: 0, seconds: 12.3 } },
  notifications: [],
  activity: [],
};

let calls: string[] = [];

function stubFetch() {
  calls = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const body = url.includes("/api/approvals") ? [] : HOME;
    return {
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => body,
      text: async () => JSON.stringify(body),
    } as unknown as Response;
  }) as typeof globalThis.fetch;
}

function countOf(fragment: string) {
  return calls.filter((u) => u.includes(fragment)).length;
}

/** 让微任务与 effect 链充分展开——若有轮询循环，这段时间足以累积上百次。 */
async function settle(ms = 250) {
  await new Promise((r) => setTimeout(r, ms));
}

function renderView() {
  return renderWithRouter(<ProjectHomeView />);
}

describe("ProjectHomeView 数据加载", () => {
  beforeEach(() => {
    stubFetch();
  });

  it("挂载后 /api/project/home 恰好请求 1 次（无限轮询回归锁）", async () => {
    renderView();
    await waitFor(() => expect(screen.getByText("测试项目")).toBeTruthy());
    await settle();

    expect(countOf("/api/project/home")).toBe(1);
  });

  it("挂载后 /api/approvals 恰好请求 1 次", async () => {
    renderView();
    await waitFor(() => expect(screen.getByText("测试项目")).toBeTruthy());
    await settle();

    expect(countOf("/api/approvals")).toBe(1);
  });

  it("总请求数恰为 2（两个端点各一次）", async () => {
    renderView();
    await waitFor(() => expect(screen.getByText("测试项目")).toBeTruthy());
    await settle();

    // 精确断言而非上限断言：写成 `toBeLessThanOrEqual(4)` 时，缺陷版本的
    // 2 次 home + 2 次 approvals 也落在范围内 —— 那条断言是**假绿**的，
    // 抓不到缺陷。这里必须与修复后行为严格一致。
    // （若日后启用 StrictMode，开发态会双调用，届时需同步调整为 4。）
    expect(calls.length).toBe(2);
  });

  it("仍会把当前项目写入最近项目列表（拆分 effect 未丢功能）", async () => {
    renderView();
    await waitFor(() => expect(screen.getByText("测试项目")).toBeTruthy());
    await settle();

    const stored = JSON.parse(localStorage.getItem("ra.recentProjects") || "[]");
    expect(stored).toEqual([{ name: "测试项目", root: "D:/ws/proj" }]);
  });

  it("数据正常渲染：资源消耗与门禁卡片都在", async () => {
    renderView();
    await waitFor(() => expect(screen.getByText("测试项目")).toBeTruthy());

    expect(screen.getByText("证据条件允许进入综合写作")).toBeTruthy();
    expect(screen.getByText("$0.500")).toBeTruthy();
  });
});
