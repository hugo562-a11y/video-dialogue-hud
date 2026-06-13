"""純計算工具函式，不依賴任何 UI 或外部狀態。"""
from __future__ import annotations

import os


def parse_time_seconds(value) -> float | None:
    text = str(value).strip().replace("～", "-").replace("~", "-")
    if not text:
        return None
    if "-" in text:
        text = text.split("-", 1)[0].strip()
    try:
        parts = [p.strip() for p in text.split(":")]
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except ValueError:
        return None


def parse_time_range(value) -> tuple[float | None, float | None]:
    text = str(value).strip().replace("～", "-").replace("~", "-")
    if "-" in text:
        start_text, end_text = text.rsplit("-", 1)
        start = parse_time_seconds(start_text)
        end = parse_time_seconds(end_text)
        return start, end
    start = parse_time_seconds(text)
    if start is None:
        return None, None
    return start, start + 3.0


def format_timecode(seconds: float) -> str:
    seconds = max(0, float(seconds))
    whole = int(seconds)
    frac = seconds - whole
    hh, rem = divmod(whole, 3600)
    mm, ss = divmod(rem, 60)
    ss_text = f"{ss + frac:05.2f}" if frac >= 0.005 else f"{ss:02d}"
    if hh:
        return f"{hh:02d}:{mm:02d}:{ss_text}"
    return f"{mm:02d}:{ss_text}"


def format_time_range(start: float, end: float) -> str:
    return f"{format_timecode(start)} - {format_timecode(end)}"


def frame_to_seconds(frame_idx: int, fps: float) -> float:
    return max(0.0, (max(1, int(frame_idx)) - 1) / max(fps or 30, 1))


def seconds_to_frame(seconds: float, fps: float, total_frames: int | None = None) -> int:
    frame = int(max(0.0, float(seconds)) * max(fps or 30, 1)) + 1
    if total_frames:
        frame = min(int(total_frames), frame)
    return max(1, frame)


def normalize_time_ranges(ranges, min_duration: float = 0.03) -> list[tuple[float, float]]:
    cleaned = []
    for start, end in ranges or []:
        if start is None or end is None:
            continue
        start = max(0.0, float(start))
        end = max(start, float(end))
        if end - start >= min_duration:
            cleaned.append((start, end))
    cleaned.sort()
    merged = []
    for start, end in cleaned:
        if not merged or start > merged[-1][1] + 0.01:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(s, e) for s, e in merged]


def time_range_overlaps(start, end, ranges) -> bool:
    if start is None or end is None:
        return False
    return any(start < cut_end and end > cut_start for cut_start, cut_end in ranges or [])


def available_output_path(base_path: str) -> str:
    if not os.path.exists(base_path):
        return base_path
    root, ext = os.path.splitext(base_path)
    idx = 1
    while True:
        candidate = f"{root}_{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
        idx += 1


def find_column(columns, candidates: list[str]):
    normalized = [(col, str(col).strip().lower()) for col in columns]
    for col, low in normalized:
        for candidate in candidates:
            if candidate in low:
                return col
    return None


class ToolTip:
    delay_ms = 400

    def __init__(self, widget, text: str):
        self._widget = widget
        self._text = text
        self._tw = None
        self._after_id = None
        widget.bind("<Enter>", self._on_enter, add=True)
        widget.bind("<Leave>", self._on_leave, add=True)

    def _on_enter(self, _event=None):
        self._after_id = self._widget.after(self.delay_ms, self._show)

    def _on_leave(self, _event=None):
        self._hide()
        if self._after_id:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tw:
            return
        import tkinter as tk
        self._tw = tk.Toplevel(self._widget)
        self._tw.wm_overrideredirect(True)
        self._tw.attributes("-topmost", True)
        self._tw.configure(bg="#333333")
        label = tk.Label(
            self._tw, text=self._text,
            fg="#F0F0F0", bg="#333333", font=("Microsoft JhengHei UI", 10),
            padx=6, pady=2,
        )
        label.pack()
        self._tw.update_idletasks()
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 2
        # Keep within screen bounds
        sw = self._widget.winfo_screenwidth()
        tw = self._tw.winfo_reqwidth()
        if x + tw > sw:
            x = sw - tw - 4
        self._tw.geometry(f"+{x}+{y}")

    def _hide(self):
        if self._tw:
            try:
                self._tw.destroy()
            except Exception:
                pass
            self._tw = None
