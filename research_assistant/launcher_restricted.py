"""Restricted launcher — expires after 3 months (2026-09-15)."""

import sys
from datetime import date

EXPIRE_DATE = date(2026, 9, 15)


def check_expiry():
    today = date.today()
    if today > EXPIRE_DATE:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "已过期",
                f"此版本已于 {EXPIRE_DATE.isoformat()} 过期，请联系作者获取新版本。"
            )
            root.destroy()
        except Exception:
            print(f"此版本已于 {EXPIRE_DATE.isoformat()} 过期，请联系作者获取新版本。")
        sys.exit(1)

    remaining = (EXPIRE_DATE - today).days
    print(f"授权有效期至 {EXPIRE_DATE.isoformat()}（剩余 {remaining} 天）")


if __name__ == "__main__":
    check_expiry()
    from research_assistant.launcher import main
    main()
