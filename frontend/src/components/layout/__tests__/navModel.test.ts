/* 导航收敛模型（R15）：段边界前缀匹配、六项侧栏定义、聚合组 tab 布局。
 * 纯逻辑 node 测试——这是「13 入口全部可达且激活态正确」的验收核心。
 */
import { describe, expect, it } from "vitest";
import {
  findGroupLayout,
  isChatEntry,
  isNavActive,
  isPathWithin,
  NAV_ITEMS,
} from "@/components/layout/navModel";

describe("isPathWithin（段边界感知前缀匹配）", () => {
  it("精确命中与子路径命中", () => {
    expect(isPathWithin("/tasks", ["/tasks"])).toBe(true);
    expect(isPathWithin("/tasks/", ["/tasks"])).toBe(true);
    expect(isPathWithin("/threads/deep-id", ["/threads"])).toBe(true);
  });

  it("同前缀兄弟路径不误命中（/tasks vs /tasksx）", () => {
    expect(isPathWithin("/tasksx", ["/tasks"])).toBe(false);
    expect(isPathWithin("/artifacts", ["/artifact"])).toBe(false);
  });

  it("根路径只匹配根自身", () => {
    expect(isPathWithin("/", ["/"])).toBe(true);
    expect(isPathWithin("/chat", ["/"])).toBe(false);
    expect(isPathWithin("/anything", ["/"])).toBe(false);
  });
});

describe("NAV_ITEMS（六项侧栏）", () => {
  it("共 6 项且入口路由唯一", () => {
    expect(NAV_ITEMS).toHaveLength(6);
    const tos = NAV_ITEMS.map((n) => n.to);
    expect(new Set(tos).size).toBe(6);
    expect(tos).toEqual(["/", "/chat", "/tasks", "/research", "/papers", "/settings"]);
  });

  it("聚合组覆盖全部成员路由；独立项只认自己", () => {
    const byTo = new Map(NAV_ITEMS.map((n) => [n.to, n]));
    // 迭代2：任务中心 = tasks(+board/history) + scheduler + analysis + notifications
    expect(byTo.get("/tasks")!.match).toEqual([
      "/tasks",
      "/scheduler",
      "/analysis",
      "/notifications",
    ]);
    // 研究工作台 = research + threads + changes
    expect(byTo.get("/research")!.match).toEqual(["/research", "/threads", "/changes"]);
    // 资料库 = papers + sources + artifacts
    expect(byTo.get("/papers")!.match).toEqual(["/papers", "/sources", "/artifacts"]);
    // 独立项
    expect(byTo.get("/")!.match).toEqual(["/"]);
    expect(byTo.get("/chat")!.match).toEqual(["/chat"]);
    expect(byTo.get("/settings")!.match).toEqual(["/settings"]);
  });

  it("会话入口被标记为审批角标承载者", () => {
    const chat = NAV_ITEMS.find((n) => n.to === "/chat")!;
    expect(isChatEntry(chat)).toBe(true);
    expect(isChatEntry(NAV_ITEMS[0]!)).toBe(false);
  });
});

describe("isNavActive（聚合组激活态）", () => {
  const byTo = new Map(NAV_ITEMS.map((n) => [n.to, n]));
  const tasks = byTo.get("/tasks")!;
  const research = byTo.get("/research")!;
  const library = byTo.get("/papers")!;
  const home = byTo.get("/")!;

  it("任务中心：三个成员页及深链均高亮", () => {
    expect(isNavActive("/tasks", tasks)).toBe(true);
    expect(isNavActive("/scheduler", tasks)).toBe(true);
    expect(isNavActive("/analysis", tasks)).toBe(true);
  });

  it("成员页之间互不串扰", () => {
    expect(isNavActive("/scheduler", research)).toBe(false);
    expect(isNavActive("/analysis", library)).toBe(false);
    expect(isNavActive("/changes", tasks)).toBe(false);
    expect(isNavActive("/sources", research)).toBe(false);
  });

  it("研究工作台：线程深链 /threads/:id 高亮该组", () => {
    expect(isNavActive("/threads/t-123", research)).toBe(true);
    expect(isNavActive("/changes", research)).toBe(true);
  });

  it("资料库：三成员页高亮", () => {
    expect(isNavActive("/papers", library)).toBe(true);
    expect(isNavActive("/sources", library)).toBe(true);
    expect(isNavActive("/artifacts", library)).toBe(true);
  });

  it("总览只在根路径高亮", () => {
    expect(isNavActive("/", home)).toBe(true);
    expect(isNavActive("/settings", home)).toBe(false);
  });
});

describe("findGroupLayout（聚合组二级 tab）", () => {
  it("任务中心组：5 分区 + 分析运行，顺序稳定（迭代2）", () => {
    const layout = findGroupLayout("/scheduler");
    expect(layout?.key).toBe("task-center");
    expect(layout?.tabs.map((t) => t.to)).toEqual([
      "/tasks",
      "/tasks/board",
      "/scheduler",
      "/tasks/history",
      "/notifications",
      "/analysis",
    ]);
    expect(layout?.tabs.map((t) => t.label)).toEqual([
      "进行中",
      "看板",
      "计划",
      "历史",
      "通知",
      "分析运行",
    ]);
  });

  it("任务中心新分区路由命中同一组", () => {
    expect(findGroupLayout("/tasks/board")?.key).toBe("task-center");
    expect(findGroupLayout("/tasks/history")?.key).toBe("task-center");
    expect(findGroupLayout("/notifications")?.key).toBe("task-center");
  });

  it("研究工作台组含线程深链页", () => {
    expect(findGroupLayout("/threads/t-abc")?.key).toBe("workbench");
    expect(findGroupLayout("/changes")?.tabs.map((t) => t.to)).toEqual([
      "/research",
      "/threads",
      "/changes",
    ]);
  });

  it("资料库组三 tab", () => {
    expect(findGroupLayout("/sources")?.key).toBe("library");
    expect(findGroupLayout("/artifacts")?.tabs).toHaveLength(3);
  });

  it("非聚合页返回 null（总览/会话/设置不挂 tab 条）", () => {
    for (const p of ["/", "/chat", "/settings"]) {
      expect(findGroupLayout(p)).toBeNull();
    }
  });
});
