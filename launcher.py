#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影片對話 HUD 工具 — 環境啟動器
雙擊 啟動.bat 執行。偵測環境、一鍵安裝缺少套件、啟動主程式。
"""
from __future__ import annotations
import sys
import os
import subprocess
import threading
import shutil
import importlib
import webbrowser
import tkinter as tk
from pathlib import Path

ROOT   = Path(__file__).parent
PYTHON = sys.executable

# ── 顏色 ──────────────────────────────────────────────────────────────────────
BG    = "#111827"
BG2   = "#1F2937"
BG3   = "#374151"
FG    = "#F9FAFB"
DIM   = "#9CA3AF"
GREEN = "#22C55E"
RED   = "#EF4444"
GOLD  = "#FBBF24"
BLUE  = "#60A5FA"

FONT  = ("Microsoft JhengHei UI", 10)
FONTB = ("Microsoft JhengHei UI", 10, "bold")
FONTH = ("Microsoft JhengHei UI", 14, "bold")
FONTS = ("Microsoft JhengHei UI",  9)

# ── 偵測項目 ──────────────────────────────────────────────────────────────────
# (id, 顯示名稱, 必要, pip 套件名稱列表 or None, 說明/連結)
ITEMS: list[tuple] = [
    ("python",        "Python 3.10+",             True,  None,                 "https://www.python.org/downloads/"),
    ("pip_ok",        "pip 套件管理員",             True,  None,                 "隨 Python 自動安裝"),
    ("customtkinter", "customtkinter（UI 框架）",   True,  ["customtkinter"],     None),
    ("PIL",           "Pillow（圖像處理）",          True,  ["pillow"],            None),
    ("cv2",           "OpenCV（影片處理）",          True,  ["opencv-python"],     None),
    ("numpy",         "NumPy",                     True,  ["numpy"],             None),
    ("pandas",        "pandas（表格資料處理）",       True,  ["pandas"],            None),
    ("ultralytics",   "Ultralytics YOLOv8",        True,  ["ultralytics"],       None),
    ("torch",         "PyTorch",                   True,  None,                 "https://pytorch.org/get-started/locally/"),
    ("faster_whisper","Faster-Whisper（語音辨識）", True,  ["faster-whisper"],    None),
    ("openpyxl",      "openpyxl（Excel 支援）",     False, ["openpyxl"],          None),
    ("resemblyzer",   "Resemblyzer（聲紋分群）",     False, ["resemblyzer"],       None),
    ("sklearn",       "scikit-learn（分群演算法）",  False, ["scikit-learn"],      None),
    ("sounddevice",   "sounddevice（音訊預覽）",    False, ["sounddevice"],       None),
    ("ffmpeg",        "ffmpeg（影片合成）",          True,  None,                 "https://www.gyan.dev/ffmpeg/builds/"),
    ("gpu",           "NVIDIA GPU / CUDA",          False, None,                 None),
]


def _check(item_id: str) -> tuple[str, str]:
    """返回 (status, detail)，status = 'ok' | 'error' | 'warn'"""
    if item_id == "python":
        ok = sys.version_info >= (3, 10)
        v  = ".".join(str(x) for x in sys.version_info[:3])
        return ("ok" if ok else "error"), v

    if item_id == "pip_ok":
        r = subprocess.run([PYTHON, "-m", "pip", "--version"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return "ok", r.stdout.split()[1]
        return "error", "未找到"

    if item_id == "ffmpeg":
        p = shutil.which("ffmpeg")
        if p:
            return "ok", p
        return "error", "未找到 — 請下載後加入系統 PATH"

    if item_id == "gpu":
        try:
            import torch  # noqa: PLC0415
            if torch.cuda.is_available():
                return "ok", torch.cuda.get_device_name(0)
            return "warn", "無 CUDA GPU（自動改用 CPU，功能完整但較慢）"
        except Exception:
            return "warn", "無法偵測（PyTorch 未安裝）"

    try:
        mod = importlib.import_module(item_id)
        ver = getattr(mod, "__version__", "")
        return "ok", ver or "已安裝"
    except ImportError:
        return "error", "未安裝"


# ── UI ────────────────────────────────────────────────────────────────────────
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("影片對話 HUD 工具 — 環境檢查")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._results:    dict[str, tuple[str, str]] = {}
        self._autofix:    list[str] = []
        self._link_urls:  dict[str, str] = {}   # tag_name -> url

        self._build_ui()
        # 先設定大小，update 後再置中（避免 winfo_screen 在視窗未繪製前回傳 0）
        self.geometry("560x600")
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = max(0, (sw - 560) // 2)
        y  = max(0, (sh - 600) // 2)
        self.geometry(f"560x600+{x}+{y}")
        # 強制視窗顯示到最前面
        self.lift()
        self.attributes("-topmost", True)
        self.after(800, lambda: self.attributes("-topmost", False))
        self.focus_force()
        self.after(300, self._start_check)

    # ── 建立 UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 標題
        tk.Label(self, text="影片對話 HUD 工具",
                 bg=BG, fg=FG, font=FONTH).pack(pady=(18, 2))
        self._subtitle = tk.Label(self, text="正在偵測環境，請稍候…",
                                  bg=BG, fg=DIM, font=FONTS)
        self._subtitle.pack()

        # 分隔
        tk.Frame(self, bg=BG3, height=1).pack(fill="x", padx=20, pady=10)

        # 偵測結果文字框
        outer = tk.Frame(self, bg=BG2, bd=0)
        outer.pack(fill="both", expand=True, padx=20)
        self._txt = tk.Text(
            outer, bg=BG2, fg=FG, font=FONT,
            relief="flat", bd=0, wrap="word",
            padx=14, pady=10,
            state="disabled", cursor="arrow",
            selectbackground=BG3,
        )
        sb = tk.Scrollbar(outer, command=self._txt.yview,
                          bg=BG3, troughcolor=BG2, width=10)
        self._txt.configure(yscrollcommand=sb.set)
        self._txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 文字 tag
        self._txt.tag_configure("ok",    foreground=GREEN)
        self._txt.tag_configure("error", foreground=RED)
        self._txt.tag_configure("warn",  foreground=GOLD)
        self._txt.tag_configure("dim",   foreground=DIM)
        self._txt.tag_configure("bold",  font=FONTB)
        self._txt.tag_configure("link",  foreground=BLUE, underline=True)

        # 進度條
        self._bar_canvas = tk.Canvas(self, bg=BG3, height=4,
                                     highlightthickness=0, bd=0)
        self._bar_canvas.pack(fill="x", padx=20, pady=(8, 0))
        self._bar_canvas.bind("<Configure>", lambda _e: self._draw_bar(self._bar_ratio))
        self._bar_ratio = 0.0

        # 分隔
        tk.Frame(self, bg=BG3, height=1).pack(fill="x", padx=20, pady=8)

        # 按鈕列
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=(0, 16))

        self._btn_fix = tk.Button(
            btn_row, text="自動安裝缺少套件",
            command=self._do_install,
            bg="#92400E", fg="white", font=FONTB,
            activebackground="#B45309", activeforeground="white",
            relief="flat", padx=14, pady=7,
            cursor="hand2", state="disabled",
        )
        self._btn_fix.pack(side="left", padx=6)

        self._btn_launch = tk.Button(
            btn_row, text="   啟動程式   ",
            command=self._launch,
            bg="#1E3A5F", fg="#6B7280", font=FONTB,
            activebackground="#2563EB", activeforeground="white",
            relief="flat", padx=14, pady=7,
            cursor="arrow", state="disabled",
        )
        self._btn_launch.pack(side="left", padx=6)

    # ── 工具方法 ──────────────────────────────────────────────────────────────
    def _draw_bar(self, ratio: float):
        self._bar_ratio = ratio
        self._bar_canvas.update_idletasks()
        w = self._bar_canvas.winfo_width()
        h = self._bar_canvas.winfo_height()
        self._bar_canvas.delete("all")
        if w > 0:
            self._bar_canvas.create_rectangle(
                0, 0, int(w * ratio), h, fill=BLUE, outline="")

    def _write(self, text: str, *tags):
        self._txt.configure(state="normal")
        self._txt.insert("end", text, tags if tags else ())
        self._txt.see("end")
        self._txt.configure(state="disabled")

    def _clear_text(self):
        self._txt.configure(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.configure(state="disabled")

    def _add_link_tag(self, tag: str, url: str):
        self._link_urls[tag] = url
        self._txt.tag_configure(tag, foreground=BLUE, underline=True)
        self._txt.tag_bind(tag, "<Enter>",
                           lambda _e: self._txt.configure(cursor="hand2"))
        self._txt.tag_bind(tag, "<Leave>",
                           lambda _e: self._txt.configure(cursor="arrow"))
        self._txt.tag_bind(tag, "<Button-1>",
                           lambda _e, u=url: webbrowser.open(u))

    # ── 偵測流程 ──────────────────────────────────────────────────────────────
    def _start_check(self):
        self._clear_text()
        self._autofix.clear()
        self._link_urls.clear()
        self._results.clear()
        self._btn_fix.configure(state="disabled")
        self._btn_launch.configure(state="disabled", bg="#1E3A5F",
                                   fg="#6B7280", cursor="arrow")
        self._subtitle.configure(text="正在偵測環境，請稍候…")
        self._draw_bar(0.0)
        threading.Thread(target=self._check_thread, daemon=True).start()

    def _check_thread(self):
        n_err = 0
        total = len(ITEMS)

        for i, (iid, label, required, pip_pkgs, note) in enumerate(ITEMS):
            status, detail = _check(iid)
            self._results[iid] = (status, detail)
            if status == "error":
                if required:
                    n_err += 1
                if pip_pkgs:
                    self._autofix.extend(pip_pkgs)

            self.after(0, self._show_row, i, iid, label, required,
                       status, detail, pip_pkgs, note, (i + 1) / total)

        self.after(0, self._finish_check, n_err)

    def _show_row(self, _i, iid, label, required,
                  status, detail, pip_pkgs, note, progress):
        icon = {"ok": "✔", "error": "✘", "warn": "△"}[status]
        opt  = "" if required else "（選用）"

        self._write(f"  {icon} ", status)
        self._write(label, "bold")
        self._write(f" {opt}\n", "dim")
        self._write(f"      {detail}\n", "dim")

        if status == "error" and note:
            if note.startswith("http"):
                link_tag = f"link_{iid}"
                self._add_link_tag(link_tag, note)
                self._write("      → 點此開啟說明頁面\n", link_tag)
            else:
                self._write(f"      → {note}\n", "dim")

        self._draw_bar(progress)

    def _finish_check(self, n_err: int):
        self._write("\n")
        if n_err == 0:
            self._write("  所有必要項目已就緒。\n", "ok")
            self._subtitle.configure(text="環境正常 — 可啟動程式", fg=GREEN)
            self._btn_launch.configure(
                state="normal", bg="#15803D", fg="white",
                activebackground="#16A34A", cursor="hand2")
        else:
            self._write(f"  尚有 {n_err} 個必要項目未安裝。\n", "error")
            self._subtitle.configure(
                text=f"有 {n_err} 個問題待解決", fg=RED)

        if self._autofix:
            self._write(f"  按「自動安裝缺少套件」可一鍵安裝 pip 套件。\n", "dim")
            self._btn_fix.configure(state="normal", bg="#D97706")

        self._draw_bar(1.0)

    # ── 安裝流程 ──────────────────────────────────────────────────────────────
    def _do_install(self):
        pkgs = list(self._autofix)
        if not pkgs:
            return
        self._btn_fix.configure(state="disabled", text="安裝中…")
        self._btn_launch.configure(state="disabled")
        self._clear_text()
        threading.Thread(target=self._install_thread, args=(pkgs,),
                         daemon=True).start()

    def _install_thread(self, pkgs: list[str]):
        self.after(0, self._write,
                   "正在安裝套件，請稍候（可能需要幾分鐘）…\n\n", "dim")
        failed = []
        for j, pkg in enumerate(pkgs):
            self.after(0, self._write, f"pip install {pkg}\n", "bold")
            r = subprocess.run(
                [PYTHON, "-m", "pip", "install", pkg],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                self.after(0, self._write, f"  ✔ {pkg} 安裝完成\n", "ok")
            else:
                self.after(0, self._write, f"  ✘ {pkg} 安裝失敗\n", "error")
                snippet = (r.stderr or r.stdout)[-400:].strip()
                self.after(0, self._write, f"  {snippet}\n\n", "dim")
                failed.append(pkg)
            self.after(0, self._draw_bar, (j + 1) / len(pkgs))

        self.after(0, self._write, "\n安裝完成，重新偵測環境…\n", "dim")
        self.after(0, self._btn_fix.configure,)  # reset in _start_check
        self.after(800, self._start_check)
        self.after(0, self._btn_fix.configure, {"text": "自動安裝缺少套件"})

    # ── 啟動主程式 ────────────────────────────────────────────────────────────
    def _launch(self):
        self.destroy()
        subprocess.Popen(
            [PYTHON, str(ROOT / "main.py")],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )


if __name__ == "__main__":
    app = Launcher()
    app.mainloop()
