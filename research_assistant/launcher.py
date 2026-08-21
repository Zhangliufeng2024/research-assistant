"""GUI launcher for Research Assistant — config dialog + web server startup."""

import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ResearchAssistant"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "https://apihub.agnes-ai.com/v1",
    "LLM_MODEL": "agnes-2.0-flash",
    "LLM_PROVIDER": "OpenAI",
    "IMAGE_API_KEY": "",
    "IMAGE_BASE_URL": "https://apihub.agnes-ai.com/v1",
    "IMAGE_MODEL": "agnes-image-2.1-flash",
    "IMAGE_REVIEW_MODEL": "agnes-2.0-flash",
    "PARALLEL_API_KEY": "",
    "SEMANTIC_SCHOLAR_API_KEY": "",
}

HOST = "127.0.0.1"
PORT = 8000


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            merged = {**DEFAULTS, **saved}
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def apply_config(cfg: dict) -> None:
    for key, value in cfg.items():
        if value:
            os.environ[key] = value


def show_config_dialog(cfg: dict) -> dict | None:
    """Show tkinter config dialog. Returns updated config or None if cancelled."""
    import tkinter as tk
    from tkinter import messagebox

    result = [None]

    root = tk.Tk()
    root.title("研究助手 — 配置")
    root.resizable(False, False)

    # Center window
    w, h = 520, 480
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    # Style
    bg = "#fafafa"
    root.configure(bg=bg)
    label_opts = {"bg": bg, "font": ("Microsoft YaHei UI", 9), "anchor": "w"}
    entry_opts = {"font": ("Consolas", 9), "relief": "solid", "bd": 1}
    section_opts = {"bg": bg, "font": ("Microsoft YaHei UI", 9, "bold"), "anchor": "w", "fg": "#2563eb"}

    entries = {}
    row = 0

    frame = tk.Frame(root, bg=bg, padx=24, pady=16)
    frame.pack(fill="both", expand=True)

    # Title
    tk.Label(frame, text="研究助手 — 首次使用配置", bg=bg,
             font=("Microsoft YaHei UI", 13, "bold"), anchor="w").grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(0, 12))
    row += 1

    # Section: LLM
    tk.Label(frame, text="语言模型（必填）", **section_opts).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
    row += 1

    fields_required = [
        ("LLM API 密钥 *", "LLM_API_KEY", ""),
        ("API 地址", "LLM_BASE_URL", ""),
        ("模型名称", "LLM_MODEL", ""),
    ]

    for label_text, key, _ in fields_required:
        tk.Label(frame, text=label_text, **label_opts).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        e = tk.Entry(frame, width=42, **entry_opts)
        e.insert(0, cfg.get(key, DEFAULTS.get(key, "")))
        if key == "LLM_API_KEY":
            e.configure(show="*")
        e.grid(row=row, column=1, sticky="w", pady=2)
        entries[key] = e
        row += 1

    # Section: Image
    tk.Label(frame, text="图像生成（可选）", **section_opts).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(12, 4))
    row += 1

    fields_image = [
        ("图像 API 密钥", "IMAGE_API_KEY"),
        ("图像 API 地址", "IMAGE_BASE_URL"),
    ]

    for label_text, key in fields_image:
        tk.Label(frame, text=label_text, **label_opts).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        e = tk.Entry(frame, width=42, **entry_opts)
        e.insert(0, cfg.get(key, DEFAULTS.get(key, "")))
        if "KEY" in key:
            e.configure(show="*")
        e.grid(row=row, column=1, sticky="w", pady=2)
        entries[key] = e
        row += 1

    # Section: Search
    tk.Label(frame, text="搜索与研究（可选）", **section_opts).grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(12, 4))
    row += 1

    fields_search = [
        ("Parallel API Key", "PARALLEL_API_KEY"),
        ("Semantic Scholar Key", "SEMANTIC_SCHOLAR_API_KEY"),
    ]

    for label_text, key in fields_search:
        tk.Label(frame, text=label_text, **label_opts).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        e = tk.Entry(frame, width=42, **entry_opts)
        e.insert(0, cfg.get(key, DEFAULTS.get(key, "")))
        if "KEY" in key:
            e.configure(show="*")
        e.grid(row=row, column=1, sticky="w", pady=2)
        entries[key] = e
        row += 1

    # Button
    def on_save():
        api_key = entries["LLM_API_KEY"].get().strip()
        if not api_key:
            messagebox.showerror("错误", "LLM API 密钥不能为空！")
            return

        new_cfg = {}
        for key, entry in entries.items():
            val = entry.get().strip()
            new_cfg[key] = val

        # Fill hidden defaults
        new_cfg["LLM_PROVIDER"] = DEFAULTS["LLM_PROVIDER"]
        new_cfg["IMAGE_MODEL"] = DEFAULTS["IMAGE_MODEL"]
        new_cfg["IMAGE_REVIEW_MODEL"] = DEFAULTS["IMAGE_REVIEW_MODEL"]

        result[0] = new_cfg
        root.destroy()

    btn_frame = tk.Frame(frame, bg=bg)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=(20, 0))

    tk.Button(btn_frame, text="保存并启动", command=on_save,
              font=("Microsoft YaHei UI", 10), bg="#2563eb", fg="white",
              relief="flat", padx=24, pady=6, cursor="hand2").pack()

    root.protocol("WM_DELETE_WINDOW", lambda: (result.__setitem__(0, None), root.destroy()))
    root.mainloop()

    return result[0]


def get_work_dir() -> Path:
    """Determine the working directory for output files."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd().resolve()


def setup_bundled_skills(work_dir: Path):
    """Copy bundled .claude skills to the working directory (PyInstaller builds)."""
    import shutil

    if getattr(sys, "frozen", False):
        # In a frozen exe, MEIPASS holds the extracted bundle
        bundle_dir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        bundle_dir = Path(__file__).parent.parent

    source = bundle_dir / ".claude"
    dest = work_dir / ".claude"

    if source.exists() and source.is_dir():
        try:
            shutil.copytree(source, dest, dirs_exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not copy skills: {e}")


def start_server(work_dir: Path):
    """Start the uvicorn server in the foreground."""
    os.chdir(str(work_dir))

    import uvicorn
    uvicorn.run(
        "research_assistant.web.app:create_app",
        factory=True,
        host=HOST,
        port=PORT,
        log_level="info",
    )


def main():
    cfg = load_config()

    need_config = not cfg.get("LLM_API_KEY")

    if need_config:
        cfg = show_config_dialog(cfg)
        if cfg is None:
            print("用户取消配置，退出。")
            sys.exit(0)
        save_config(cfg)

    apply_config(cfg)

    work_dir = get_work_dir()

    # Ensure output directory and skills are set up
    (work_dir / "writing_outputs").mkdir(exist_ok=True)
    setup_bundled_skills(work_dir)
    print("研究助手启动中...")
    print(f"  工作目录: {work_dir}")
    print(f"  模型: {cfg.get('LLM_MODEL', 'unknown')}")
    print(f"  地址: http://{HOST}:{PORT}")
    print(f"  配置文件: {CONFIG_FILE}")
    print()

    # Open browser after a short delay
    def open_browser():
        time.sleep(2)
        webbrowser.open(f"http://{HOST}:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        start_server(work_dir)
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
