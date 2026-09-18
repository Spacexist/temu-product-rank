# -*- coding: utf-8 -*-
"""厨房收纳 EXE 壳：调本机 venv 跑日更，预览 HTML，上传 datta-picks。"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPE = ROOT / "pipeline"
CF = ROOT / "cf-site"
PY = Path(r"F:\Clip\venv\Scripts\python.exe")
sys.path.insert(0, str(CF))
sys.path.insert(0, str(PIPE))

from uploadedCF import (  # noqa: E402
    inject_nav,
    parse_day,
    upsert_days,
    write_pages,
    deploy,
)


def py_bin() -> str:
    return str(PY) if PY.is_file() else sys.executable


class App:
    """customtkinter 主窗口。"""

    def __init__(self) -> None:
        import customtkinter as ctk
        from tkinter import filedialog

        self.ctk = ctk
        self.filedialog = filedialog
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title("厨房收纳日更")
        self.root.geometry("760x560")
        self.busy = False

        pad = {"padx": 12, "pady": 6}
        ctk.CTkLabel(self.root, text="CSV 丢 inbox 或点导入。过滤词在 words/banned.txt。切分按店铺。").pack(anchor="w", **pad)

        row = ctk.CTkFrame(self.root, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkButton(row, text="导入 CSV 并跑今天", command=self.on_import_run).pack(side="left")
        ctk.CTkButton(row, text="跑 inbox 最新", command=self.on_inbox).pack(side="left", padx=8)
        ctk.CTkButton(row, text="打开预览 HTML", command=self.on_preview).pack(side="left")

        row2 = ctk.CTkFrame(self.root, fg_color="transparent")
        row2.pack(fill="x", **pad)
        ctk.CTkButton(row2, text="筛选结果 → 明天训练", command=self.on_publish).pack(side="left")
        ctk.CTkButton(row2, text="上传 Cloudflare", command=self.on_upload).pack(side="left", padx=8)
        ctk.CTkButton(row2, text="打开过滤词", command=self.on_words).pack(side="left")

        date_row = ctk.CTkFrame(self.root)
        date_row.pack(fill="x", **pad)
        ctk.CTkLabel(date_row, text="发布日期").pack(side="left", padx=8)
        self.iso_var = ctk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        ctk.CTkEntry(date_row, textvariable=self.iso_var, width=120).pack(side="left", padx=4)
        ctk.CTkButton(date_row, text="今天", width=60, command=self._today).pack(side="left", padx=4)

        self.log = ctk.CTkTextbox(self.root, height=340)
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._write("准备好了。第一天 inbox/918.csv 可直接跑。\n")

    def _today(self) -> None:
        self.iso_var.set(datetime.now().strftime("%Y-%m-%d"))

    def _write(self, msg: str) -> None:
        self.log.insert("end", msg)
        self.log.see("end")

    def _ask(self, title: str, patterns) -> Path | None:
        desktop = Path.home() / "Desktop"
        chosen = self.filedialog.askopenfilename(
            title=title,
            initialdir=str(desktop if desktop.is_dir() else Path.home()),
            filetypes=patterns,
        )
        return Path(chosen).resolve() if chosen else None

    def _run_bg(self, fn) -> None:
        if self.busy:
            self._write("正在跑，等一下。\n")
            return
        self.busy = True

        def wrap() -> None:
            try:
                fn()
            except Exception as exc:
                self.root.after(0, lambda: self._write(f"失败: {exc}\n"))
            finally:
                self.busy = False

        threading.Thread(target=wrap, daemon=True).start()

    def _daily(self, extra: list[str]) -> None:
        cmd = [py_bin(), "-u", str(PIPE / "daily.py"), *extra]
        self.root.after(0, lambda: self._write(f"$ {' '.join(cmd)}\n"))
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            self.root.after(0, lambda m=line: self._write(m))
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"daily.py exit={code}")

    def on_import_run(self) -> None:
        path = self._ask("今天的厨房收纳 CSV", [("表格", "*.csv *.xlsx *.xls"), ("全部", "*.*")])
        if path is None:
            return
        iso, _short, _label = parse_day(path)
        self.iso_var.set(iso)
        self._run_bg(lambda: self._daily(["--today", str(path)]))

    def on_inbox(self) -> None:
        self._run_bg(lambda: self._daily([]))

    def on_preview(self) -> None:
        htmls = sorted((ROOT / "output").glob("*_分享.html"), key=lambda p: p.stat().st_mtime)
        if not htmls:
            self._write("还没有分享页，先跑今天。\n")
            return
        webbrowser.open(htmls[-1].as_uri())
        self._write(f"预览 {htmls[-1]}\n")

    def on_publish(self) -> None:
        path = self._ask(
            "筛选后的 HTML 或 CSV（删掉的不会进明天训练）",
            [("筛选结果", "*.html *.csv"), ("全部", "*.*")],
        )
        if path is None:
            return
        self._run_bg(lambda: self._daily(["--publish", str(path), "--iso", self.iso_var.get().strip()]))

    def on_words(self) -> None:
        p = ROOT / "words" / "banned.txt"
        os.startfile(p)  # noqa: S606  Windows 记事本打开

    def on_upload(self) -> None:
        htmls = sorted((ROOT / "output").glob("*_分享.html"), key=lambda p: p.stat().st_mtime)
        if not htmls:
            path = self._ask("要上传的 HTML", [("HTML", "*.html"), ("全部", "*.*")])
            if path is None:
                return
        else:
            path = htmls[-1]
        iso = self.iso_var.get().strip() or parse_day(path)[0]
        short = parse_day(path)[1]

        def job() -> None:
            self.root.after(0, lambda: self._write("生成上传包并写 data_cache…\n"))
            self._daily(["--bundle", str(path), "--iso", iso])
            html = path.read_text(encoding="utf-8")
            html = inject_nav(html, iso)
            upsert_days(iso, short, iso)
            write_pages(html, iso, short)
            self.root.after(0, lambda: self._write("wrangler deploy…\n"))
            url = deploy()
            self.root.after(0, lambda: self._write(f"已上线 {url}\n已缓存 {ROOT / 'data_cache' / iso}\n"))
            webbrowser.open(url)

        self._run_bg(job)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
