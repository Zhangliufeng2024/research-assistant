# R6 计划：Windows 安装程序 + 图形化模型设置

日期：2026-08-22 ｜ 前置：R5（会话工作台 + 桌面壳）已发布 v3.1.0

## 背景与目标

R5 之后两个普通用户门槛：

1. **分发**：便携 zip 需解压、无快捷方式/卸载器 → 做 **Inno Setup 安装程序**（setup.exe：
   开始菜单 + 桌面快捷方式、控制面板卸载）。
2. **模型配置**：唯一入口是手写工作目录 `.env`（`config.load_project_env`），无图形界面
   → 做**「设置」视图**：服务商预设、Base URL、模型名、掩码 Key、测试连接，保存写回
   工作目录 `.env`。

## 决策

| # | 决策 | 理由 |
|---|------|------|
| D1 | 设置存储沿用 `.env`（不发明 JSON 配置库） | 复用 `load_project_env`；CLI/Web/桌面三种入口同一份配置 |
| D2 | API Key 读接口只返回掩码（`sk-a***f4`），全文不回浏览器 | 本机应用也不做无谓泄露面 |
| D3 | `POST /settings` 行式改写 `.env`：已知键原地更新，未知行/注释原样保留 | 用户手工加的其它变量不能丢 |
| D4 | 测试连接 = 用表单当前值临时建 client 发一次最小请求，**不落盘** | 先验证再保存的直觉顺序 |
| D5 | 未配置 Key 时 chat 视图顶部横幅引导去设置页（桌面壳无需特判） | 前端一处逻辑，Web/桌面通吃 |
| D6 | 版本升至 **3.2.0**，Release 附 setup.exe | 新功能 minor bump |

## 交付物

1. `research_assistant/web/settings.py` — GET/POST `/api/settings`、POST `/api/settings/test`
2. `static/js/views/settings.js` + 导航/路由注册 + chat 未配置横幅
3. pytest：掩码、.env 保留无关行、test 连接（mock client）
4. `build/installer.iss` + winget 安装 Inno Setup → `dist/ResearchAssistant_setup_3.2.0.exe`
5. 全量回归 + exe 冒烟 + GitHub Release v3.2.0

## 明确不做（本轮）

- IMAGE_* / PARALLEL_API_KEY 的图形化配置（设置页留「高级：直接编辑 .env」提示即可）
- 自动更新器；macOS/Linux 打包；开机自启勾选项
