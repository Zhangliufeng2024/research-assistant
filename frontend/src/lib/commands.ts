/* slash 命令解析（方案 4）：纯函数，可 vitest 覆盖。

约定（与 chat.ts 分派协定）：
- 命令以 `/` 开头且紧跟一个非空命令名；
- 余文分为 `key=value` 键值对（budget）或单词 arg（role/model/skill）；
- `/help` 输出 `COMMAND_CATALOG` 的帮助文案。

parseCommand 仅负责“识别 + 解析为结构”，不执行副作用——执行落到
chatStore.send 里下发到 chat.py（`/budget` 写全局 .env；`/role`、`/plan`、`/help`
作为前置 context / 提醒）。这样前后端都可独立测试：前端测命令解析，
后端测分派。 */

/** 支持的命令名 → 分类。 */
export type CommandKind =
  | "budget"
  | "model"
  | "role"
  | "skill"
  | "plan"
  | "help"
  | "unknown";

export interface ParsedCommand {
  /** 去掉前导 `/` 与命令名，原样保存（含命令名） */
  raw: string;
  /** 命令名（不含 `/`） */
  name: string;
  kind: CommandKind;
  /**
   * 键值对参数。budget={\"cost\":\"50\",...}；
   * role/model/skill={value:\"planner\"}；plan={}；help={}。
   * unknown 命令里原样透传未知键。
   */
  args: Record<string, string>;
  /** 非法用法 / 未知命令时的解释文案（无错误时 undefined） */
  error?: string;
}

/** 命令目录：名称 / 说明 / 参数提示，`/help` 渲染用。 */
export interface CommandDef {
  name: string;
  kind: CommandKind;
  description: string;
  usage: string;
}

export const COMMAND_CATALOG: CommandDef[] = [
  {
    name: "budget",
    kind: "budget",
    description: "为本次运行设置实时预算上限（覆盖 RA_MAX_*）",
    usage: "/budget cost=<USD> tokens=<N> turns=<N> wall_seconds=<N>",
  },
  {
    name: "model",
    kind: "model",
    description: "临时切换本次对话的写作/推理模型",
    usage: "/model gpt-4o",
  },
  {
    name: "role",
    kind: "role",
    description: "为本次回合指定 Agent 角色 persona（需提前注册）",
    usage: "/role planner",
  },
  {
    name: "skill",
    kind: "skill",
    description: "注入一个技能 SKILL.md 作为前置 context (26 个专业技能)",
    usage: "/skill scientific-writing",
  },
  {
    name: "plan",
    kind: "plan",
    description: "要求助手先输出计划方案并等待确认再执行（对应方案 1 Plan 门）",
    usage: "/plan",
  },
  {
    name: "help",
    kind: "help",
    description: "显示可用命令列表",
    usage: "/help",
  },
];

const _CAT_BY_NAME = new Map(COMMAND_CATALOG.map((c) => [c.name, c]));

/** 输入是否以 slash 命令开头（`/\S`） */
export function isCommand(text: string): boolean {
  return /^\s*\/\S/.test(text);
}

/** 从 `text` 中提取出 `name` 与 `rest`（去掉命令名后的剩余字符串）。 */
function _split(text: string): { name: string; rest: string } {
  const trimmed = text.replace(/^\s*\/\s*/, "").trimStart();
  const m = trimmed.match(/^(\S+)/);
  const name = m ? m[1] : "";
  const rest = trimmed.slice(name.length).trim();
  return { name, rest };
}

/** `key=value key2=value2` → map；不带 `=` 的 token 归入 `_i` positional。 */
function _parseArgs(rest: string): Record<string, string> {
  if (!rest) return {};
  const args: Record<string, string> = {};
  const parts = rest.split(/\s+/);
  for (const part of parts) {
    const eq = part.indexOf("=");
    if (eq > 0) {
      const k = part.slice(0, eq);
      const v = part.slice(eq + 1);
      if (k) args[k] = v;
    } else if (part) {
      args["_i"] = part; // single positional arg（role/model/skill）
    }
  }
  return args;
}

const _BUDGET_RE = /^(cost|tokens|turns|wall_seconds)$/;

export function parseCommand(text: string): ParsedCommand {
  const raw = text ?? "";
  if (!isCommand(raw)) {
    return { raw, name: "", kind: "unknown", args: {}, error: "not a command" };
  }
  const { name, rest } = _split(raw);
  const cat = _CAT_BY_NAME.get(name);

  if (!cat) {
    // 透传未知命令：name + 原文 args，让下游决定是否提示“未知命令”。
    const args = _parseArgs(rest);
    return {
      raw,
      name,
      kind: "unknown",
      args,
      error: `Unknown command: /${name}. Run /help for available commands.`,
    };
  }

  switch (cat.kind) {
    case "budget": {
      const args = _parseArgs(rest);
      for (const k of Object.keys(args)) {
        if (k !== "_i" && !_BUDGET_RE.test(k)) {
          return { raw, name, kind: "budget", args, error: `Unknown budget key: ${k}` };
        }
      }
      // 校验数值型
      for (const k of Object.keys(args)) {
        const v = args[k];
        if (k === "_i") {
          return { raw, name, kind: "budget", args, error: "budget takes only key=value pairs" };
        }
        const num = Number(v);
        if (!Number.isFinite(num) || num <= 0) {
          return { raw, name, kind: "budget", args, error: `budget ${k}= must be a positive number` };
        }
      }
      return { raw, name, kind: "budget", args };
    }
    case "model":
    case "role":
    case "skill": {
      const args = _parseArgs(rest);
      if (args["_i"]) {
        return { raw, name, kind: cat.kind, args: { value: args["_i"] } };
      }
      // 允许 key=value 形式兜底
      return { raw, name, kind: cat.kind, args };
    }
    case "plan":
    case "help":
      return { raw, name, kind: cat.kind, args: {} };
    default:
      return { raw, name, kind: "unknown", args: {}, error: "unhandled command" };
  }
}

/** `/help` 渲染用的帮助文本。 */
export function formatHelp(): string {
  const lines = COMMAND_CATALOG.map((c) => `  /${c.name.padEnd(7)} ${c.description}\n    用法：${c.usage}`).join("\n");
  return `可用命令：\n${lines}`;
}

/** Composer 命令下拉（方案 4 前端）：输入正在敲一个未含空格的命令 token
 * （如 `/`、`/bu`）时给出候选；已带空格/参数视为命令已敲完，不再提示。
 * 纯函数，vitest 覆盖。 */
export function commandSuggestions(value: string): CommandDef[] {
  const m = value.match(/^\/([a-zA-Z0-9_]*)$/);
  if (!m) return [];
  const prefix = (m[1] ?? "").toLowerCase();
  return COMMAND_CATALOG.filter((c) => c.name.startsWith(prefix));
}
