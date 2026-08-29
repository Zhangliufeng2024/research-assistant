#!/usr/bin/env python3
"""Research Assistant CLI Tool — command-line interface for research and writing."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from .agent import RunConfig, run_agent
from .config import (
    build_llm_client,
    generate_session_dir_name,
    load_project_env,
    resolve_model,
)
from .core import (
    create_data_context_message,
    ensure_output_folder,
    get_api_key,
    get_data_files,
    load_system_instructions,
    process_data_files,
    setup_claude_skills,
)
from .display import format_status_line, format_tool_result_tag, format_tool_start
from .mcp_client import McpServerConnection, connect_mcp_servers, parse_servers_config
from .models import TokenUsage
from .orchestrator import run_orchestrated_generation
from .retry import (
    ContextLimitError,
    HeartbeatTimeoutError,
    ModelConfigError,
    get_max_retries,
)
from .steer import SteerReader
from .tools.registry import ToolRegistry
from .utils import detect_paper_reference, find_existing_papers


def _list_runs(output_folder: Path) -> list[tuple[str, str]]:
    """List paper directories with their run.json status (newest first)."""
    runs: list[tuple[str, str]] = []
    if not output_folder.exists():
        return runs
    for d in sorted(output_folder.iterdir(), key=lambda p: p.stat().st_mtime,
                     reverse=True):
        if not d.is_dir():
            continue
        status = "?"
        rf = d / "run.json"
        if rf.exists():
            try:
                status = json.loads(rf.read_text(encoding="utf-8")).get("status", "?")
            except Exception:  # noqa: BLE001 — 尽力而为：run.json 损坏按「?」展示，不影响目录列表
                pass
        runs.append((d.name, status))
    return runs


async def main(track_token_usage: bool = False) -> TokenUsage | None:
    """Main CLI loop for the research assistant."""
    cwd = Path.cwd().resolve()
    load_project_env(cwd)

    try:
        get_api_key()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    package_dir = Path(__file__).parent.absolute()
    setup_claude_skills(package_dir, cwd)
    output_folder = ensure_output_folder(cwd)

    system_instructions = load_system_instructions(cwd)
    system_instructions += "\n\n" + f"""
IMPORTANT - WORKING DIRECTORY:
- Your working directory is: {cwd}
- ALWAYS create writing_outputs folder in this directory: {cwd}/writing_outputs/
- NEVER write to /tmp/ or any other temporary directory
- All paper outputs MUST go to: {cwd}/writing_outputs/<timestamp>_<description>/

IMPORTANT - CONVERSATION CONTINUITY:
- If the prompt includes [CONTEXT: You are currently working on a paper in: ...], continue editing that paper
- If no such context is provided, this is a NEW paper request
- Each new chat session should start with a new paper unless context says otherwise

IMPORTANT - SKILL SCRIPT PATHS:
- Scientific schematics:  python {cwd}/.claude/skills/scientific-schematics/scripts/generate_schematic.py
- Image generation:       python {cwd}/.claude/skills/generate-image/scripts/generate_image.py
- Web search/research:    python {cwd}/.claude/skills/parallel-web/scripts/parallel_web.py
- Academic paper lookup:  python {cwd}/.claude/skills/research-lookup/scripts/research_lookup.py
- Infographics:           python {cwd}/.claude/skills/infographics/scripts/generate_infographic.py
- PDF to images:          python {cwd}/.claude/skills/scientific-slides/scripts/pdf_to_images.py
- Citation management:    python {cwd}/.claude/skills/citation-management/scripts/doi_to_bibtex.py
All skill scripts MUST be called with these absolute paths.
NOTE: Image generation auto-detects provider from IMAGE_API_KEY (nvapi- = NVIDIA, else OpenAI-compatible).

MID-EXECUTION STEERING:
- You may receive messages prefixed with [USER STEER]: during your work.
- These are real-time corrections or guidance from the user typed while you are working.
- When you see a steer message, acknowledge it briefly and adjust your approach immediately.
- Prioritize steer instructions over your current plan.
"""

    auto_continue = os.environ.get("RA_AUTO_CONTINUE", "true").lower() in ("true", "1", "yes")
    multi_agent = os.environ.get("RA_MULTI_AGENT", "false").lower() in ("true", "1", "yes")

    model = resolve_model()

    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation_tokens = 0
    total_cache_read_tokens = 0

    current_paper_path = None

    async def _run_query(prompt: str, *, silent: bool = False) -> None:
        nonlocal total_input_tokens, total_output_tokens
        nonlocal total_cache_creation_tokens, total_cache_read_tokens

        llm_client = build_llm_client(model=model)
        tool_registry = ToolRegistry(work_dir=str(cwd))

        # G-2：MCP 外部工具接入——RA_MCP_SERVERS 非空时连接并注册远端工具。
        # 失败的服务器内部已记录并跳过（部分可用优于全或无），接入本身是
        # 增强能力，整体失败也不阻断会话。
        mcp_connections: list[McpServerConnection] = []
        raw_servers = os.getenv("RA_MCP_SERVERS", "")
        if raw_servers.strip():
            try:
                mcp_connections = await connect_mcp_servers(
                    tool_registry, parse_servers_config(raw_servers),
                )
                if mcp_connections:
                    print(f"MCP: 已接入 {len(mcp_connections)} 个服务器", flush=True)
            except Exception as exc:  # noqa: BLE001 — 增强能力失败不阻断主流程
                print(f"MCP 服务器接入失败（忽略）: {exc}", flush=True)

        async def _on_text(text: str) -> None:
            if not silent:
                print(text, end="", flush=True)

        async def _on_tool_start(name: str, args: dict) -> None:
            if not silent:
                line = format_tool_start(name, args)
                print(f"\n  {line}", end="", flush=True)

        async def _on_tool_use(name: str, args: dict, result: str) -> None:
            if not silent:
                tag = format_tool_result_tag(result)
                print(tag, flush=True)

        async def _on_turn_start(turn: int, elapsed: float, usage: TokenUsage) -> None:
            if not silent:
                status = format_status_line(turn, elapsed, usage)
                print(f"\n{status}", flush=True)

        async def _on_steer_injected(msg: str) -> None:
            print(f'\n  >> Steer: "{msg}"', flush=True)

        steer_queue: asyncio.Queue = asyncio.Queue()
        steer_reader = SteerReader()
        if not silent and sys.stdin.isatty():
            steer_reader.start(steer_queue, asyncio.get_event_loop())

        # Interactive approvals ride the same stdin channel as steering:
        # a PRE_TOOL_USE ask prints the request; the next typed line
        # (y/yes = allow, anything else = deny) answers it.
        approver = None
        if (os.environ.get("RA_APPROVAL_MODE", "off").strip().lower()
                == "interactive"):
            from .kernel.approval import QueueApprover

            def _print_approval(text: str) -> None:
                print(f"\n  ⚠ {text}\n    允许执行? 输入 y 允许，其他任意内容拒绝",
                      flush=True)

            approver = QueueApprover(steer_queue, timeout=120.0,
                                     printer=_print_approval)

        try:
            result = await run_agent(
                prompt=prompt,
                system_prompt=system_instructions,
                llm_client=llm_client,
                tools=tool_registry,
                config=RunConfig(
                    auto_continue=auto_continue,
                    approver=approver,
                ),
                on_text=_on_text,
                on_tool_start=_on_tool_start,
                on_tool_use=_on_tool_use,
                on_turn_start=_on_turn_start,
                steer_queue=steer_queue,
                on_steer_injected=_on_steer_injected,
            )

            if track_token_usage:
                total_input_tokens += result.token_usage.input_tokens
                total_output_tokens += result.token_usage.output_tokens
                total_cache_creation_tokens += result.token_usage.cache_creation_input_tokens
                total_cache_read_tokens += result.token_usage.cache_read_input_tokens

        except HeartbeatTimeoutError as exc:
            print(
                f"\n\nAgent appears stuck: no output for {exc.timeout:.0f}s "
                f"(after {get_max_retries()} auto-retries).",
                flush=True,
            )
            print("Options:")
            print("  [r] Retry the query from scratch")
            print("  [c] Continue with a new prompt")
            print("  [q] Quit")
            try:
                choice = input("Choice [r/c/q]: ").strip().lower()
            except EOFError:
                choice = "q"
            if choice == "r":
                print("\nRetrying...\n")
                await _run_query(prompt, silent=silent)
            elif choice == "q":
                raise SystemExit(0) from None

        except ContextLimitError:
            print(
                "\n\nThe conversation has exceeded the model's context limit.\n"
                "Start a new session or reduce input size.\n",
                flush=True,
            )

        except ModelConfigError as exc:
            print(f"\n\nModel configuration error: {exc}\n", flush=True)

        finally:
            steer_reader.stop()
            await llm_client.close()
            for conn in mcp_connections:
                await conn.close()

    async def _run_multi_agent_query(prompt: str) -> None:
        nonlocal current_paper_path

        if not current_paper_path:
            target_dir = generate_session_dir_name(prompt)
            paper_output_dir = output_folder / target_dir
        else:
            paper_output_dir = Path(current_paper_path)

        async for update in run_orchestrated_generation(
            query=prompt,
            model=model,
            work_dir=cwd,
            output_dir=paper_output_dir,
        ):
            if isinstance(update, dict):
                if update.get("type") == "text":
                    print(update.get("content", ""), end="", flush=True)
                elif update.get("type") == "progress":
                    stage = update.get("stage", "")
                    msg = update.get("message", "")
                    if msg:
                        print(f"\n[{stage}] {msg}", flush=True)
                elif update.get("type") == "result":
                    paper_dir = update.get("paper_directory", "")
                    if paper_dir:
                        current_paper_path = paper_dir

        if not current_paper_path:
            try:
                paper_dirs = [d for d in output_folder.iterdir() if d.is_dir()]
                if paper_dirs:
                    most_recent = max(paper_dirs, key=lambda d: d.stat().st_mtime)
                    if time.time() - most_recent.stat().st_mtime < 30:
                        current_paper_path = str(most_recent)
            except Exception:  # noqa: BLE001 — 尽力而为：探测最新论文目录失败不阻断会话启动
                pass

    # Welcome message
    print("=" * 70)
    print("Research Assistant CLI")
    print("=" * 70)
    print("\nWelcome! I'm your scientific writing assistant.")
    print(f"\n  Working directory: {cwd}")
    print(f"  Output folder: {output_folder}")
    print(f"  Model: {model}")
    print(f"  Multi-agent: {'ENABLED' if multi_agent else 'DISABLED'}")
    print("\nType 'exit' to quit, 'help' for usage tips.")
    print("=" * 70)
    print()

    try:
        while True:
            try:
                user_input = input("\n> ").strip()

                if user_input.lower() in ("exit", "quit"):
                    print("\nGoodbye!")
                    if track_token_usage:
                        return TokenUsage(
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            cache_creation_input_tokens=total_cache_creation_tokens,
                            cache_read_input_tokens=total_cache_read_tokens,
                        )
                    return None

                if user_input.lower() == "help":
                    _print_help()
                    continue

                if user_input.lower().startswith("multi-agent"):
                    parts = user_input.lower().split()
                    if len(parts) > 1 and parts[1] in ("on", "off", "true", "false", "1", "0"):
                        multi_agent = parts[1] in ("on", "true", "1")
                        print(f"\nMulti-agent mode: {'ENABLED' if multi_agent else 'DISABLED'}")
                    else:
                        print(f"\nMulti-agent mode: {'ENABLED' if multi_agent else 'DISABLED'}")
                    continue

                if user_input.lower().startswith("resume"):
                    parts = user_input.split()
                    runs = _list_runs(output_folder)
                    if len(parts) == 1:
                        if not runs:
                            print("\nNo previous runs found.")
                        else:
                            print("\nRuns (newest first):")
                            for name, status in runs[:15]:
                                print(f"  {name}  [{status}]")
                            print("\nUse: resume <name-prefix>")
                        continue
                    prefix = parts[1]
                    match = next(
                        (name for name, _ in runs if name.startswith(prefix)), None,
                    )
                    if match:
                        current_paper_path = str(output_folder / match)
                        status = dict(runs).get(match, "?")
                        print(f"\nResuming: {match} [{status}]")
                    else:
                        print(f"\nNo run matching '{prefix}'. Try 'resume' to list.")
                    continue

                if not user_input:
                    continue

                existing_papers = find_existing_papers(output_folder)

                new_paper_keywords = [
                    "new paper", "start fresh", "create new", "different paper", "another paper",
                    "new presentation", "new poster",
                ]
                is_new_paper_request = any(kw in user_input.lower() for kw in new_paper_keywords)

                detected_paper_path = None
                if not is_new_paper_request:
                    detected_paper_path = detect_paper_reference(user_input, existing_papers)
                    if detected_paper_path and str(detected_paper_path) != current_paper_path:
                        current_paper_path = str(detected_paper_path)
                        print(f"\nDetected reference to: {detected_paper_path.name}")
                    elif detected_paper_path and str(detected_paper_path) == current_paper_path:
                        print(f"Continuing with: {Path(current_paper_path).name}\n")

                data_context = ""
                data_files = get_data_files(cwd)
                intent = "writing"

                if data_files and not current_paper_path and (is_new_paper_request or not current_paper_path):
                    print(f"\nFound {len(data_files)} file(s) in data folder.")
                    print("Creating paper directory...\n")

                    directory_prompt = (
                        f"Create a new paper directory structure in writing_outputs/ with subfolders: "
                        f"drafts/, final/, references/, figures/, data/, sources/ and a progress.md file. "
                        f"Based on: {user_input}"
                    )
                    await _run_query(directory_prompt, silent=False)
                    print("\n")

                    await asyncio.sleep(1)
                    try:
                        paper_dirs = [d for d in output_folder.iterdir() if d.is_dir()]
                        if paper_dirs:
                            most_recent = max(paper_dirs, key=lambda d: d.stat().st_mtime)
                            if time.time() - most_recent.stat().st_mtime < 15:
                                current_paper_path = str(most_recent)
                    except Exception:  # noqa: BLE001 — 尽力而为：论文目录轮询失败静等下一轮
                        pass

                    if current_paper_path:
                        processed_info = process_data_files(cwd, data_files, current_paper_path, delete_originals=True)
                        if processed_info:
                            data_context = create_data_context_message(processed_info)
                            print("Files processed. Starting paper generation...\n")

                    contextual_prompt = f"""[CONTEXT: You are working on a paper in: {current_paper_path}]
{data_context}
{user_input}"""

                elif data_files and current_paper_path and not is_new_paper_request:
                    processed_info = process_data_files(cwd, data_files, current_paper_path, delete_originals=True)
                    if processed_info:
                        data_context = create_data_context_message(processed_info)
                    contextual_prompt = f"""[CONTEXT: You are currently working on a paper in: {current_paper_path}]
{data_context}
User request: {user_input}"""

                elif is_new_paper_request:
                    current_paper_path = None
                    print("Starting a new paper...\n")
                    contextual_prompt = user_input

                elif current_paper_path:
                    contextual_prompt = f"""[CONTEXT: You are currently working on a paper in: {current_paper_path}]
User request: {user_input}"""

                else:
                    classify_client = build_llm_client(model=model)
                    try:
                        intent = await _classify_intent(user_input, classify_client)
                    finally:
                        await classify_client.close()
                    if intent == "question":
                        contextual_prompt = (
                            "[MODE: QUESTION — answer directly, do NOT create any files or folders]\n"
                            + user_input
                        )
                    else:
                        contextual_prompt = user_input

                print()
                if multi_agent:
                    await _run_multi_agent_query(contextual_prompt)
                else:
                    await _run_query(contextual_prompt)
                print()

                if not current_paper_path and not data_files and intent == "writing":
                    try:
                        paper_dirs = [d for d in output_folder.iterdir() if d.is_dir()]
                        if paper_dirs:
                            most_recent = max(paper_dirs, key=lambda d: d.stat().st_mtime)
                            if time.time() - most_recent.stat().st_mtime < 10:
                                current_paper_path = str(most_recent)
                                print(f"\nWorking on: {most_recent.name}")
                    except Exception:  # noqa: BLE001 — 尽力而为：论文目录轮询失败不阻断主循环
                        pass

            except KeyboardInterrupt:
                print("\n\nInterrupted. Type 'exit' to quit or continue with a new prompt.")
                continue
            except Exception as e:
                print(f"\nError: {e}")
                print("Please try again or type 'exit' to quit.")
    except Exception as e:  # noqa: BLE001 — 真实错误上报：内层逐轮兜底之外逃逸的异常须可见
        print(f"\nSession terminated due to an unexpected error: {e}")

    if track_token_usage:
        return TokenUsage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cache_creation_input_tokens=total_cache_creation_tokens,
            cache_read_input_tokens=total_cache_read_tokens,
        )
    return None


async def _classify_intent(user_input: str, llm_client) -> str:
    """Use the LLM to classify user input as 'question' or 'writing'."""
    classification_prompt = (
        "You are an intent classifier. The user sent a message to a scientific writing assistant. "
        "Determine if the user wants to:\n"
        "- 'question': Ask a question, get information, have a conversation, or any request "
        "that does NOT require creating files/documents (e.g. '什么是FEM?', 'explain LCA', "
        "'介绍下自己', 'hello', 'thanks')\n"
        "- 'writing': Create, write, generate, edit, or revise a document, paper, report, "
        "poster, slides, or any file-producing task (e.g. '写一篇论文', 'write a paper on FEM', "
        "'generate a literature review')\n\n"
        "Reply with ONLY the single word 'question' or 'writing'. Nothing else."
    )
    try:
        response = await llm_client.chat(
            messages=[{"role": "user", "content": user_input}],
            system=classification_prompt,
            max_tokens=10,
        )
        result = response.content.strip().lower()
        if "writing" in result:
            return "writing"
        if "question" in result:
            return "question"
    except Exception:  # noqa: BLE001 — 合理降级：分类失败按默认 writing 走，不阻断用户输入
        pass
    return "writing"


def _print_help():
    print("\n" + "=" * 70)
    print("HELP - Research Assistant CLI")
    print("=" * 70)
    print("\nI can help you with:")
    print("  - Scientific papers (Word .docx, IMRaD)")
    print("  - Literature reviews")
    print("  - Peer review feedback")
    print("  - Research lookup")
    print("  - Document manipulation")
    print("\nCommands:")
    print("  multi-agent on|off  Toggle parallel agent execution")
    print("  resume [prefix]     List/resume a previous run (run.json state)")
    print("  new paper           Start a fresh paper")
    print("  exit/quit           End session")
    print("\nData Files:")
    print("  Place files in data/ folder to include in your paper")
    print("  .docx/.tex -> drafts/, images -> figures/, data -> data/")
    print("=" * 70)


def cli_main():
    """Entry point for the CLI script."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
