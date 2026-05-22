# pip install customtkinter opencv-python ultralytics pandas openpyxl pillow numpy

try:
    import tqdm
    tqdm.tqdm.monitor_interval = 0
except Exception:
    pass

import atexit
import os
import queue
import random
import shutil
import string
import subprocess
import tempfile
import threading
import time

import cv2
import customtkinter as ctk
import numpy as np
import pandas as pd
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk
from tkinter import filedialog, messagebox
from ultralytics import YOLO


APP_TITLE = "影片對話 HUD 工具"
MODEL_PATH = "yolov8n.pt"
FONT_NAME = "NotoSansCJKtc-Bold.otf"
MAX_PREVIEW_SIZE = 720
SILENCE_SPEAKER = "無講話"
SILENCE_TEXT = "（無講話）"
MIN_SILENCE_SECONDS = 0.45

_SAFE_PATH_MAP = {}
_CLEANUP_PATHS = []


def get_safe_path(path):
    """Give OpenCV an ASCII path when the original path contains non-ASCII text."""
    if not path:
        return path
    if path in _SAFE_PATH_MAP:
        return _SAFE_PATH_MAP[path]
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        ext = os.path.splitext(path)[1]
        safe_name = "".join(random.choices(string.ascii_letters, k=12)) + ext
        safe_path = os.path.join(tempfile.gettempdir(), safe_name)
        try:
            os.link(path, safe_path)
        except Exception:
            shutil.copy2(path, safe_path)
        _SAFE_PATH_MAP[path] = safe_path
        _CLEANUP_PATHS.append(safe_path)
        return safe_path


@atexit.register
def cleanup_temp_files():
    for path in _CLEANUP_PATHS:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def parse_time_seconds(value):
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


def parse_time_range(value):
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


def format_time_range(start, end):
    return f"{format_timecode(start)} - {format_timecode(end)}"


def format_timecode(seconds):
    seconds = max(0, float(seconds))
    whole = int(seconds)
    frac = seconds - whole
    hh, rem = divmod(whole, 3600)
    mm, ss = divmod(rem, 60)
    if frac >= 0.005:
        ss_text = f"{ss + frac:05.2f}"
    else:
        ss_text = f"{ss:02d}"
    if hh:
        return f"{hh:02d}:{mm:02d}:{ss_text}"
    return f"{mm:02d}:{ss_text}"


def frame_to_seconds(frame_idx, fps):
    return max(0.0, (max(1, int(frame_idx)) - 1) / max(fps or 30, 1))


def seconds_to_frame(seconds, fps, total_frames=None):
    frame = int(max(0.0, float(seconds)) * max(fps or 30, 1)) + 1
    if total_frames:
        frame = min(int(total_frames), frame)
    return max(1, frame)


def normalize_time_ranges(ranges, min_duration=0.03):
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
    return [(start, end) for start, end in merged]


def time_range_overlaps(start, end, ranges):
    if start is None or end is None:
        return False
    return any(start < cut_end and end > cut_start for cut_start, cut_end in ranges or [])


def available_output_path(base_path):
    if not os.path.exists(base_path):
        return base_path
    root, ext = os.path.splitext(base_path)
    idx = 1
    while True:
        candidate = f"{root}_{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
        idx += 1


def find_column(columns, candidates):
    normalized = [(col, str(col).strip().lower()) for col in columns]
    for col, low in normalized:
        for candidate in candidates:
            if candidate in low:
                return col
    return None


class DataProcessor:
    def __init__(self):
        self.df = None
        self.path = None

    def load_data(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".csv":
                try:
                    self.df = pd.read_csv(file_path, encoding="utf-8-sig")
                except UnicodeDecodeError:
                    self.df = pd.read_csv(file_path, encoding="big5")
            elif ext in (".xls", ".xlsx"):
                self.df = pd.read_excel(file_path)
            else:
                return False, "只支援 CSV、XLS、XLSX 對話表。"
        except Exception as exc:
            return False, f"讀取失敗：{exc}"

        self.path = file_path
        return True, f"已載入 {len(self.df)} 筆對話：{os.path.basename(file_path)}"

    def set_dataframe(self, df, source_name="辨識腳本"):
        self.df = df
        self.path = source_name
        return True, f"已套用 {len(self.df)} 筆對話：{source_name}"

    def has_data(self):
        return self.df is not None and not self.df.empty

    def get_columns(self):
        if not self.has_data():
            return None, None, None
        time_col = find_column(self.df.columns, ["時間", "time", "start"])
        speaker_col = find_column(self.df.columns, ["說話者", "speaker", "人物", "角色", "id"])
        text_col = find_column(self.df.columns, ["對話", "內容", "文字", "text", "content"])
        return time_col, speaker_col, text_col

    def get_unique_speakers(self):
        if not self.has_data():
            return []
        _, speaker_col, _ = self.get_columns()
        if speaker_col is None:
            return []
        values = self.df[speaker_col].dropna().astype(str).str.strip()
        return [v for v in values.unique().tolist() if v and v != SILENCE_SPEAKER]

    def get_dialogue(self, frame_idx, fps, total_frames, track_id, manual_speaker=""):
        if not self.has_data():
            return ""

        row_idx, text = self.find_dialogue_row(frame_idx, fps, track_id, manual_speaker)
        if row_idx is not None:
            return text

        return self.get_column_mapped_dialogue(frame_idx, total_frames, track_id)

    def find_dialogue_row(self, frame_idx, fps, track_id, manual_speaker=""):
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is not None and text_col is not None:
            time_sec = frame_to_seconds(frame_idx, fps)
            df = self.df.copy()
            df[time_col] = df[time_col].ffill()

            for idx, row in df.iterrows():
                speaker = str(row[speaker_col]).strip() if speaker_col is not None else ""
                if speaker == SILENCE_SPEAKER:
                    continue
                if speaker_col is not None and manual_speaker:
                    if speaker and speaker != manual_speaker:
                        continue
                start, end = parse_time_range(row[time_col])
                if start is None or end is None:
                    continue
                if start <= time_sec < end:
                    value = row[text_col]
                    if pd.isna(value):
                        return idx, ""
                    return idx, str(value).strip().strip("「」")
        return None, ""

    def add_silence_rows(self, total_duration=None, min_silence=MIN_SILENCE_SECONDS):
        if not self.has_data():
            return 0
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            return 0

        speech_rows = []
        for _, row in self.df.iterrows():
            speaker = "" if pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
            if speaker == SILENCE_SPEAKER:
                continue
            start, end = parse_time_range(row[time_col])
            if start is None or end is None or end <= start:
                continue
            speech_rows.append((start, end, row.to_dict()))
        speech_rows.sort(key=lambda item: item[0])

        rows = []
        added = 0
        last_end = 0.0
        for start, end, row_dict in speech_rows:
            if start - last_end >= min_silence:
                rows.append(self._silence_row(time_col, speaker_col, text_col, last_end, start))
                added += 1
            rows.append(row_dict)
            last_end = max(last_end, end)
        if total_duration and total_duration - last_end >= min_silence:
            rows.append(self._silence_row(time_col, speaker_col, text_col, last_end, total_duration))
            added += 1
        if added:
            self.df = pd.DataFrame(rows, columns=list(self.df.columns))
        return added

    def remove_rows_overlapping_ranges(self, ranges):
        if not self.has_data():
            return 0
        ranges = normalize_time_ranges(ranges)
        if not ranges:
            return 0
        time_col, _, _ = self.get_columns()
        if time_col is None:
            return 0

        kept_rows = []
        removed = 0
        for _, row in self.df.iterrows():
            start, end = parse_time_range(row[time_col])
            if time_range_overlaps(start, end, ranges):
                removed += 1
                continue
            kept_rows.append(row.to_dict())
        if removed:
            self.df = pd.DataFrame(kept_rows, columns=list(self.df.columns))
        return removed

    def _silence_row(self, time_col, speaker_col, text_col, start, end):
        row = {col: "" for col in self.df.columns}
        row[time_col] = format_time_range(start, end)
        row[speaker_col] = SILENCE_SPEAKER
        row[text_col] = SILENCE_TEXT
        return row

    def update_dialogue_row(self, row_idx, text):
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False
        _, _, text_col = self.get_columns()
        if text_col is None:
            return False
        self.df.at[row_idx, text_col] = text
        return True

    def update_dialogue_speaker(self, row_idx, speaker):
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False
        _, speaker_col, _ = self.get_columns()
        if speaker_col is None:
            return False
        speaker = str(speaker).strip()
        if not speaker:
            return False
        self.df.at[row_idx, speaker_col] = speaker
        return True

    def update_dialogue_time(self, row_idx, start, end, min_duration=0.05):
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False
        time_col, _, _ = self.get_columns()
        if time_col is None:
            return False
        start = max(0.0, float(start))
        end = max(0.0, float(end))
        if end - start < min_duration:
            return False
        self.df.at[row_idx, time_col] = format_time_range(start, end)
        return True

    def get_dialogue_row_values(self, row_idx):
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return "", ""
        _, speaker_col, text_col = self.get_columns()
        speaker = ""
        text = ""
        if speaker_col is not None:
            value = self.df.at[row_idx, speaker_col]
            speaker = "" if pd.isna(value) else str(value).strip()
        if text_col is not None:
            value = self.df.at[row_idx, text_col]
            text = "" if pd.isna(value) else str(value).strip().strip("「」")
        return speaker, text

    def find_dialogue_at_time(self, frame_idx, fps):
        if not self.has_data():
            return None, ""
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or text_col is None:
            return None, ""
        time_sec = frame_to_seconds(frame_idx, fps)
        df = self.df.copy()
        df[time_col] = df[time_col].ffill()
        for idx, row in df.iterrows():
            speaker = str(row[speaker_col]).strip() if speaker_col is not None else ""
            if speaker == SILENCE_SPEAKER:
                continue
            start, end = parse_time_range(row[time_col])
            if start is None or end is None:
                continue
            if start <= time_sec < end:
                value = row[text_col]
                return idx, "" if pd.isna(value) else str(value).strip().strip("「」")
        return None, ""

    def split_dialogue_row(self, row_idx, cursor_pos):
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False, "目前沒有可斷句的腳本列。", None
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or text_col is None:
            return False, "腳本需要時間點和對話內容欄位才能斷句。", None

        old_text = "" if pd.isna(self.df.at[row_idx, text_col]) else str(self.df.at[row_idx, text_col])
        cursor_pos = max(1, min(int(cursor_pos), len(old_text) - 1))
        left_text = old_text[:cursor_pos].strip()
        right_text = old_text[cursor_pos:].strip()
        if not left_text or not right_text:
            return False, "請把游標放在句子中間再斷句。", None

        start, end = parse_time_range(self.df.at[row_idx, time_col])
        if start is None or end is None or end <= start:
            return False, "這列時間格式無法斷句。", None
        ratio = len(left_text) / max(1, len(left_text) + len(right_text))
        split_at = start + (end - start) * ratio
        split_at = max(start + 0.05, min(end - 0.05, split_at))

        columns = list(self.df.columns)
        row_data = self.df.loc[row_idx].to_dict()
        first = dict(row_data)
        second = dict(row_data)
        first[time_col] = format_time_range(start, split_at)
        first[text_col] = left_text
        second[time_col] = format_time_range(split_at, end)
        second[text_col] = right_text

        rows = []
        new_second_idx = None
        for idx, row in self.df.iterrows():
            if idx == row_idx:
                rows.append(first)
                rows.append(second)
                new_second_idx = len(rows) - 1
            else:
                rows.append(row.to_dict())
        self.df = pd.DataFrame(rows, columns=columns)
        return True, "已斷成兩句。", new_second_idx

    def insert_dialogue_row(self, start, end, speaker, text):
        if not self.has_data():
            self.df = pd.DataFrame(columns=["時間點", "說話者", "對話內容"])
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            time_col, speaker_col, text_col = "時間點", "說話者", "對話內容"
            self.df = pd.DataFrame(columns=[time_col, speaker_col, text_col])

        new_row = {col: "" for col in self.df.columns}
        new_row[time_col] = format_time_range(start, end)
        new_row[speaker_col] = speaker or "人物 1"
        new_row[text_col] = text
        marker = "__new_dialogue_row__"
        new_row[marker] = True
        rows = [row.to_dict() for _, row in self.df.iterrows()]
        rows.append(new_row)
        rows.sort(key=lambda row: parse_time_range(row.get(time_col, ""))[0] or 0)
        self.df = pd.DataFrame(rows)
        new_idx = next((idx for idx, row in self.df.iterrows() if bool(row.get(marker, False))), len(rows) - 1)
        if marker in self.df.columns:
            self.df = self.df.drop(columns=[marker])
        self.df = self.df[[col for col in self.df.columns if col in list(new_row.keys()) and col != marker]]
        return new_idx

    def delete_dialogue_row(self, row_idx):
        if not self.has_data() or row_idx not in self.df.index:
            return False
        self.df = self.df.drop(index=row_idx).reset_index(drop=True)
        return True

    def merge_dialogue_rows(self, row_idx):
        if not self.has_data() or row_idx not in self.df.index:
            return False, "找不到要合併的列。"
        pos = list(self.df.index).index(row_idx)
        if pos >= len(self.df) - 1:
            return False, "最後一列沒有下一句可合併。"
        next_idx = self.df.index[pos + 1]
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or text_col is None:
            return False, "腳本格式不完整，無法合併。"
        start, _ = parse_time_range(self.df.at[row_idx, time_col])
        _, end = parse_time_range(self.df.at[next_idx, time_col])
        if start is None or end is None:
            return False, "時間格式無法合併。"
        text1 = "" if pd.isna(self.df.at[row_idx, text_col]) else str(self.df.at[row_idx, text_col]).strip()
        text2 = "" if pd.isna(self.df.at[next_idx, text_col]) else str(self.df.at[next_idx, text_col]).strip()
        self.df.at[row_idx, time_col] = format_time_range(start, end)
        if text1 == SILENCE_TEXT:
            merged_text = text2
        elif text2 == SILENCE_TEXT:
            merged_text = text1
        else:
            merged_text = text1 + text2
        self.df.at[row_idx, text_col] = merged_text
        self.df = self.df.drop(index=next_idx).reset_index(drop=True)
        return True, "已合併下一句。"

    def get_column_mapped_dialogue(self, frame_idx, total_frames, track_id):
        if not self.has_data():
            return ""
        matched_col = None
        for col in self.df.columns:
            low = str(col).lower().replace(" ", "")
            if str(track_id) == str(col) or f"id{track_id}" in low or f"人物{track_id}" in low:
                matched_col = col
                break
        if matched_col is None:
            return ""

        data_len = len(self.df)
        mapped_idx = int((frame_idx / max(1, total_frames)) * max(0, data_len - 1))
        value = self.df[matched_col].iloc[mapped_idx]
        return "" if pd.isna(value) else str(value).strip()


class VideoRenderer:
    def __init__(self, ui_callback=None):
        self.ui_callback = ui_callback
        self.yolo_model = None
        self.video_path = None
        self.data_processor = DataProcessor()

        self.settings = {
            "bubble_style": "classic",
            "bubble_pos": "auto",
        }
        self.style = {
            "font_size": 72,
            "font_color": (255, 255, 255, 255),
        }

        self.is_processing = False
        self.tracking_data = {}
        self.yolo_id_to_speaker = {}
        self.last_positions = {}
        self.bubble_offsets = {}
        self.bubble_rects = {}
        self.bubble_cache = {}
        self.person_rois = []
        self.expected_people_count = 2
        self.cut_ranges = []

        self.total_frames = 0
        self.fps = 30
        self.video_width = 0
        self.video_height = 0
        self._preview_cap = None
        self._preview_cap_path = None
        self.font_path = self._font_path()

    def _font_path(self):
        local = os.path.join(os.path.dirname(__file__), FONT_NAME)
        if os.path.exists(local):
            return local
        return "msjh.ttc"

    def ensure_model(self):
        if self.yolo_model is None:
            model_path = os.path.join(os.path.dirname(__file__), MODEL_PATH)
            self.yolo_model = YOLO(model_path if os.path.exists(model_path) else MODEL_PATH)

    def set_video_resolution(self, width, height):
        self.video_width = width
        self.video_height = height
        auto_size = max(24, min(160, int(height / 15)))
        self.style["font_size"] = auto_size
        self.bubble_cache.clear()
        return auto_size

    def _load_font(self, size):
        for candidate in (self.font_path, "msjh.ttc", "arial.ttf"):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _wrap_text(self, text, limit=14):
        text = str(text).strip()
        if not text:
            return ""
        lines = []
        current = ""
        for char in text:
            current += char
            if len(current) >= limit:
                lines.append(current)
                current = ""
        if current:
            lines.append(current)
        return "\n".join(lines)

    def get_speech_bubble_img(self, text, pos="top", track_id=0):
        style = self.settings.get("bubble_style", "classic")
        cache_key = (text, pos, track_id, style, self.style["font_size"], self.style["font_color"])
        if cache_key in self.bubble_cache:
            return self.bubble_cache[cache_key]

        scale = 3
        font_size = int(self.style["font_size"]) * scale
        font = self._load_font(font_size)
        wrapped = self._wrap_text(text)

        palette = [
            ((31, 127, 181, 235), (255, 255, 255, 255)),
            ((205, 73, 73, 235), (255, 255, 255, 255)),
            ((49, 163, 98, 235), (255, 255, 255, 255)),
            ((230, 177, 54, 240), (20, 20, 20, 255)),
            ((118, 91, 171, 235), (255, 255, 255, 255)),
            ((37, 161, 154, 235), (255, 255, 255, 255)),
        ]
        bg_col, default_text_col = palette[int(track_id) % len(palette)]
        text_col = self.style.get("font_color") or default_text_col

        measure_img = Image.new("RGBA", (1, 1))
        measure = ImageDraw.Draw(measure_img)
        bbox = measure.multiline_textbbox((0, 0), wrapped or " ", font=font, spacing=8 * scale)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        pad_x = 28 * scale
        pad_y = 18 * scale
        bubble_w = max(80 * scale, text_w + pad_x * 2)
        bubble_h = max(44 * scale, text_h + pad_y * 2)
        tail = 16 * scale
        canvas_w = bubble_w + 24 * scale
        canvas_h = bubble_h + tail + 24 * scale

        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x0 = 12 * scale
        y0 = 12 * scale if pos != "bottom" else 12 * scale + tail
        x1 = x0 + bubble_w
        y1 = y0 + bubble_h

        outline = (255, 255, 255, 230)
        if style == "oval":
            draw.ellipse([x0, y0, x1, y1], fill=bg_col, outline=outline, width=2 * scale)
        elif style == "sharp":
            draw.rectangle([x0, y0, x1, y1], fill=bg_col, outline=outline, width=2 * scale)
        elif style == "capsule":
            draw.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) // 2, fill=bg_col, outline=outline, width=2 * scale)
        elif style == "tech":
            cut = 18 * scale
            points = [(x0 + cut, y0), (x1, y0), (x1, y1 - cut), (x1 - cut, y1), (x0, y1), (x0, y0 + cut)]
            draw.polygon(points, fill=bg_col)
            draw.line(points + [points[0]], fill=outline, width=2 * scale)
        else:
            draw.rounded_rectangle([x0, y0, x1, y1], radius=14 * scale, fill=bg_col, outline=outline, width=2 * scale)

        cx = (x0 + x1) // 2
        cy = (y0 + y1) // 2
        if pos == "bottom":
            draw.polygon([(cx - tail, y0 + 2 * scale), (cx + tail, y0 + 2 * scale), (cx, y0 - tail)], fill=bg_col)
        elif pos == "left":
            draw.polygon([(x1 - 2 * scale, cy - tail), (x1 - 2 * scale, cy + tail), (x1 + tail, cy)], fill=bg_col)
        elif pos == "right":
            draw.polygon([(x0 + 2 * scale, cy - tail), (x0 + 2 * scale, cy + tail), (x0 - tail, cy)], fill=bg_col)
        else:
            draw.polygon([(cx - tail, y1 - 2 * scale), (cx + tail, y1 - 2 * scale), (cx, y1 + tail)], fill=bg_col)

        text_x = x0 + (bubble_w - text_w) // 2
        text_y = y0 + (bubble_h - text_h) // 2 - 2 * scale
        draw.multiline_text((text_x, text_y), wrapped, font=font, fill=text_col, align="center", spacing=8 * scale)

        final = img.resize((canvas_w // scale, canvas_h // scale), Image.Resampling.LANCZOS)
        bgra = cv2.cvtColor(np.array(final), cv2.COLOR_RGBA2BGRA)
        self.bubble_cache[cache_key] = bgra
        return bgra

    def draw_speech_bubble(self, frame, text, target_id, all_boxes):
        if not text:
            return
        target = next((box for box in all_boxes if box["id"] == target_id), None)
        if target is None:
            return

        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = target["bbox"]
        center_x = int((x1 + x2) / 2)
        probe = self.get_speech_bubble_img(text, "top", target_id)
        bh, bw = probe.shape[:2]
        positions = {
            "top": (center_x - bw // 2, int(y1) - bh - 8),
            "bottom": (center_x - bw // 2, int(y2) + 8),
            "left": (int(x1) - bw - 8, int(y1)),
            "right": (int(x2) + 8, int(y1)),
        }

        def blocked(px, py):
            if px < 0 or py < 0 or px + bw > fw or py + bh > fh:
                return True
            for other in all_boxes:
                if other["id"] == target_id:
                    continue
                ox1, oy1, ox2, oy2 = other["bbox"]
                if not (px + bw < ox1 or px > ox2 or py + bh < oy1 or py > oy2):
                    return True
            return False

        pos_setting = self.settings.get("bubble_pos", "auto")
        if pos_setting in positions:
            chosen = pos_setting
        else:
            order = [self.last_positions.get(target_id, "top"), "top", "bottom", "right", "left"]
            chosen = next((pos for pos in order if pos in positions and not blocked(*positions[pos])), "top")
        self.last_positions[target_id] = chosen

        bubble = self.get_speech_bubble_img(text, chosen, target_id)
        bh, bw = bubble.shape[:2]
        px, py = positions[chosen]
        dx, dy = self.bubble_offsets.get(target_id, (0, 0))
        px = max(0, min(fw - bw, px + dx))
        py = max(0, min(fh - bh, py + dy))
        self.bubble_rects[target_id] = (px, py, px + bw, py + bh)

        x_end = min(fw, px + bw)
        y_end = min(fh, py + bh)
        if x_end <= px or y_end <= py:
            return
        overlay = bubble[0:y_end - py, 0:x_end - px]
        alpha = overlay[:, :, 3] / 255.0
        for channel in range(3):
            frame[py:y_end, px:x_end, channel] = (
                alpha * overlay[:, :, channel] + (1.0 - alpha) * frame[py:y_end, px:x_end, channel]
            ).astype(np.uint8)

    def scan_video(self, max_frames=None):
        if not self.video_path:
            return
        self.is_processing = True
        self.ensure_model()
        safe_path = get_safe_path(self.video_path)
        cap = cv2.VideoCapture(safe_path)
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.video_width)
        self.video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.video_height)

        self.tracking_data = {}
        frame_count = 0
        limit = max_frames or self.total_frames
        last_person_boxes = {}
        try:
            while cap.isOpened() and self.is_processing and frame_count < limit:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_count += 1
                if self.person_rois:
                    boxes_list = self._scan_person_rois(frame, last_person_boxes)
                else:
                    results = self.yolo_model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0], verbose=False)
                    boxes_list = []
                    if results and results[0].boxes is not None and results[0].boxes.id is not None:
                        boxes = results[0].boxes.xyxy.cpu().numpy()
                        track_ids = results[0].boxes.id.cpu().int().numpy()
                        for box, track_id in zip(boxes, track_ids):
                            x1, y1, x2, y2 = box
                            head_h = min(int((x2 - x1) * 1.05), int((y2 - y1) * 0.42), int(y2 - y1))
                            bbox = (int(x1), int(y1), int(x2), int(y1 + head_h))
                            tid = int(track_id)
                            boxes_list.append({"id": tid, "bbox": bbox})
                            self._auto_assign_speaker(tid)
                self.tracking_data[frame_count] = boxes_list

                if self.ui_callback and frame_count % 5 == 0:
                    denominator = max(limit, 1)
                    self.ui_callback("progress", min(frame_count / denominator, 1.0))
        finally:
            cap.release()
            if self.person_rois:
                self._assign_default_speakers(len(self.person_rois))
            else:
                self.consolidate_tracking_ids(self.expected_people_count)
            self.is_processing = False
            if self.ui_callback:
                self.ui_callback("scan_finished", 1.0)
                self.ui_callback("progress", 1.0)

    def _scan_person_rois(self, frame, last_person_boxes):
        boxes_list = []
        fh, fw = frame.shape[:2]
        for index, roi in enumerate(self.person_rois, start=1):
            rx1, ry1, rx2, ry2 = self._clamp_roi(roi, fw, fh)
            if rx2 <= rx1 or ry2 <= ry1:
                continue
            crop = frame[ry1:ry2, rx1:rx2]
            detected = self._best_person_box(crop, rx1, ry1)
            previous = last_person_boxes.get(index)
            if detected is not None and previous is not None:
                detected = self._smooth_box(previous, detected, alpha=0.35)
            if detected is None:
                detected = previous
            if detected is None:
                detected = self._head_box_from_full_body((rx1, ry1, rx2, ry2))
            last_person_boxes[index] = detected
            boxes_list.append({"id": index, "bbox": detected})
        return boxes_list

    def _best_person_box(self, crop, offset_x, offset_y):
        if crop.size == 0:
            return None
        results = self.yolo_model.predict(crop, classes=[0], verbose=False)
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None
        boxes = results[0].boxes.xyxy.cpu().numpy()
        best = max(boxes, key=lambda box: max(0, box[2] - box[0]) * max(0, box[3] - box[1]))
        x1, y1, x2, y2 = best
        full_body = (int(x1 + offset_x), int(y1 + offset_y), int(x2 + offset_x), int(y2 + offset_y))
        return self._head_box_from_full_body(full_body)

    def _head_box_from_full_body(self, box):
        x1, y1, x2, y2 = box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        head_h = min(int(width * 1.05), int(height * 0.42), height)
        return (int(x1), int(y1), int(x2), int(y1 + head_h))

    def _smooth_box(self, old_box, new_box, alpha=0.35):
        return tuple(int((1 - alpha) * old + alpha * new) for old, new in zip(old_box, new_box))

    def _clamp_roi(self, roi, width, height):
        x1, y1, x2, y2 = roi
        x1, x2 = sorted((int(x1), int(x2)))
        y1, y2 = sorted((int(y1), int(y2)))
        x1 = max(0, min(width, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height, y1))
        y2 = max(0, min(height, y2))
        return x1, y1, x2, y2

    def _assign_default_speakers(self, max_people):
        speakers = self.data_processor.get_unique_speakers()
        self.yolo_id_to_speaker = {
            idx + 1: speakers[idx] if idx < len(speakers) else f"人物 {idx + 1}"
            for idx in range(max_people)
        }

    def consolidate_tracking_ids(self, max_people):
        max_people = max(1, int(max_people or 1))
        stats = {}
        for boxes in self.tracking_data.values():
            for box in boxes:
                x1, y1, x2, y2 = box["bbox"]
                tid = int(box["id"])
                item = stats.setdefault(tid, {"count": 0, "sum_x": 0.0, "sum_y": 0.0})
                item["count"] += 1
                item["sum_x"] += (x1 + x2) / 2
                item["sum_y"] += (y1 + y2) / 2

        if len(stats) <= max_people:
            return

        centers = []
        for tid, item in stats.items():
            count = max(item["count"], 1)
            centers.append({
                "id": tid,
                "count": count,
                "x": item["sum_x"] / count,
                "y": item["sum_y"] / count,
            })

        seeds = sorted(centers, key=lambda item: item["count"], reverse=True)[:max_people]
        seeds = sorted(seeds, key=lambda item: item["x"])

        id_map = {}
        for center in centers:
            best_index = min(
                range(len(seeds)),
                key=lambda idx: abs(center["x"] - seeds[idx]["x"]) + 0.35 * abs(center["y"] - seeds[idx]["y"]),
            )
            id_map[center["id"]] = best_index + 1

        for frame_idx, boxes in list(self.tracking_data.items()):
            merged = {}
            for box in boxes:
                new_id = id_map.get(int(box["id"]), int(box["id"]))
                x1, y1, x2, y2 = box["bbox"]
                area = max(0, x2 - x1) * max(0, y2 - y1)
                old = merged.get(new_id)
                if old is None or area > old["area"]:
                    merged[new_id] = {"id": new_id, "bbox": box["bbox"], "area": area}
            self.tracking_data[frame_idx] = [
                {"id": item["id"], "bbox": item["bbox"]}
                for item in sorted(merged.values(), key=lambda item: item["id"])
            ]

        speakers = self.data_processor.get_unique_speakers()
        self.yolo_id_to_speaker = {
            idx + 1: speakers[idx] if idx < len(speakers) else f"人物 {idx + 1}"
            for idx in range(max_people)
        }
        self.last_positions.clear()
        self.bubble_offsets.clear()
        self.bubble_cache.clear()

    def _auto_assign_speaker(self, track_id):
        if track_id in self.yolo_id_to_speaker:
            return
        speakers = self.data_processor.get_unique_speakers()
        if len(self.yolo_id_to_speaker) < len(speakers):
            self.yolo_id_to_speaker[track_id] = speakers[len(self.yolo_id_to_speaker)]

    def _text_for_track(self, frame_idx, track_id):
        speaker = self.yolo_id_to_speaker.get(track_id, "")
        return self.data_processor.get_dialogue(frame_idx, self.fps, self.total_frames, track_id, speaker)

    def set_cut_ranges(self, ranges):
        self.cut_ranges = normalize_time_ranges(ranges)

    def _frame_in_cut_ranges(self, frame_idx, fps):
        seconds = (frame_idx - 1) / max(fps or 30, 1)
        return any(start <= seconds < end for start, end in self.cut_ranges)

    def get_preview_frame(self, frame_idx):
        if not self.video_path:
            return None
        self.bubble_rects = {}
        safe_path = get_safe_path(self.video_path)
        if self._preview_cap is None or self._preview_cap_path != safe_path or not self._preview_cap.isOpened():
            if self._preview_cap is not None:
                self._preview_cap.release()
            self._preview_cap = cv2.VideoCapture(safe_path)
            self._preview_cap_path = safe_path

        cap = self._preview_cap
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx - 1))
        ret, frame = cap.read()
        if not ret:
            return None

        boxes = self.tracking_data.get(frame_idx, [])
        for box_data in boxes:
            text = self._text_for_track(frame_idx, box_data["id"])
            self.draw_speech_bubble(frame, text, box_data["id"], boxes)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return self._resize_preview(rgb)

    def _resize_preview(self, rgb):
        h, w = rgb.shape[:2]
        scale = min(MAX_PREVIEW_SIZE / max(w, 1), MAX_PREVIEW_SIZE / max(h, 1), 1.0)
        if scale < 1.0:
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
        return rgb

    def export_video(self):
        if not self.video_path or not self.tracking_data:
            return
        self.is_processing = True
        safe_path = get_safe_path(self.video_path)
        cap = cv2.VideoCapture(safe_path)
        if not cap.isOpened():
            self.is_processing = False
            if self.ui_callback:
                self.ui_callback("error_log", "影片無法開啟，匯出中止。")
                self.ui_callback("finished", 1.0, out_path="")
            return
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or self.fps or 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or self.total_frames or 1)

        real_out_path = available_output_path(os.path.splitext(self.video_path)[0] + "_hud_output.mp4")
        safe_out_path = os.path.join(tempfile.gettempdir(), "".join(random.choices(string.ascii_letters, k=12)) + "_hud.mp4")
        out = cv2.VideoWriter(safe_out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not out.isOpened():
            cap.release()
            self.is_processing = False
            if self.ui_callback:
                self.ui_callback("error_log", "影片輸出器無法建立，匯出中止。")
                self.ui_callback("finished", 1.0, out_path="")
            return

        frame_count = 0
        try:
            while cap.isOpened() and self.is_processing:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_count += 1
                if self._frame_in_cut_ranges(frame_count, fps):
                    if self.ui_callback and frame_count % 10 == 0:
                        self.ui_callback("progress", min(frame_count / max(total, 1), 1.0))
                    continue
                boxes = self.tracking_data.get(frame_count, [])
                for box_data in boxes:
                    text = self._text_for_track(frame_count, box_data["id"])
                    self.draw_speech_bubble(frame, text, box_data["id"], boxes)
                out.write(frame)
                if self.ui_callback and frame_count % 10 == 0:
                    self.ui_callback("progress", min(frame_count / max(total, 1), 1.0))
        finally:
            cap.release()
            out.release()
            duration = total / max(fps, 1)
            self._merge_audio_or_move(safe_out_path, safe_path, real_out_path, duration)
            self.is_processing = False
            if self.ui_callback:
                self.ui_callback("finished", 1.0, out_path=real_out_path)

    def _merge_audio_or_move(self, video_path, source_path, output_path, duration=None):
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            temp_audio_out = video_path.replace(".mp4", "_audio.mp4")
            cut_ranges = normalize_time_ranges(self.cut_ranges)
            if cut_ranges and duration:
                keep_ranges = []
                cursor = 0.0
                for start, end in cut_ranges:
                    start = min(max(start, 0.0), duration)
                    end = min(max(end, start), duration)
                    if start > cursor + 0.01:
                        keep_ranges.append((cursor, start))
                    cursor = max(cursor, end)
                if duration > cursor + 0.01:
                    keep_ranges.append((cursor, duration))

                if keep_ranges:
                    parts = []
                    labels = []
                    for idx, (start, end) in enumerate(keep_ranges):
                        label = f"a{idx}"
                        parts.append(f"[1:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[{label}]")
                        labels.append(f"[{label}]")
                    filter_complex = ";".join(parts + [f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[aout]"])
                    cmd = [
                        ffmpeg, "-y", "-i", video_path, "-i", source_path,
                        "-filter_complex", filter_complex,
                        "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "[aout]",
                        "-shortest", temp_audio_out,
                    ]
                else:
                    cmd = [
                        ffmpeg, "-y", "-i", video_path,
                        "-c:v", "copy", "-an", temp_audio_out,
                    ]
            else:
                cmd = [
                    ffmpeg, "-y", "-i", video_path, "-i", source_path,
                    "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0?",
                    "-shortest", temp_audio_out,
                ]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
                if result.returncode == 0 and os.path.exists(temp_audio_out):
                    shutil.move(temp_audio_out, output_path)
                    try:
                        os.remove(video_path)
                    except OSError:
                        pass
                    return
                if self.ui_callback:
                    detail = result.stderr.decode("utf-8", errors="ignore").strip().splitlines()
                    message = detail[-1] if detail else "ffmpeg 未回傳詳細錯誤。"
                    self.ui_callback("error_log", f"音訊合併失敗，將輸出無音訊影片：{message}")
            except Exception:
                if self.ui_callback:
                    self.ui_callback("error_log", "音訊合併失敗，將輸出無音訊影片。")
            try:
                if os.path.exists(temp_audio_out):
                    os.remove(temp_audio_out)
            except OSError:
                pass
        elif self.ui_callback:
            self.ui_callback("error_log", "找不到 ffmpeg，匯出影片將不含原始聲音。")
        shutil.move(video_path, output_path)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 640)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.renderer = VideoRenderer(ui_callback=self.handle_renderer_update)
        self.ui_queue = queue.Queue()
        self.preview_pil_orig = None
        self.preview_zoom = 1.0
        self.canvas_offset = [0, 0]
        self._canvas_tk_img = None
        self._canvas_mode = "pan"
        self._drag_start = (0, 0)
        self._drag_offset_start = [0, 0]
        self._drag_moved = False
        self._roi_start = (0, 0)
        self._roi_rect_id = None
        self._bubble_drag_tid = None
        self._bubble_drag_start_canvas = (0, 0)
        self._bubble_drag_start_offset = (0, 0)
        self.preview_boxes = []
        self.preview_scale_x = 1.0
        self.preview_scale_y = 1.0
        self.people_count_confirmed = False
        self.selected_dialogue_row = None
        self._loading_person_fields = False
        self.audio_scrub_var = ctk.BooleanVar(value=True)
        self.silence_seconds_var = ctk.DoubleVar(value=MIN_SILENCE_SECONDS)
        self._ffplay_process = None
        self._waveform_audio_path = None
        self._last_audio_preview_at = -1.0
        self.waveform_samples = None
        self.waveform_duration = None
        self.waveform_step_seconds = 0.01
        self.waveform_activity_intervals = []
        self.waveform_view_start = 0.0
        self.waveform_view_end = None
        self.waveform_dialogue_handles = []
        self.waveform_drag_handle = None
        self._waveform_mouse_down = False
        self._waveform_pan_start_x = 0
        self._waveform_pan_start_range = (0.0, 0.0)
        self._waveform_drag_mode = None
        self._waveform_drag_moved = False
        self._waveform_range_drag_start = None
        self.preview_playing = False
        self._preview_play_after_id = None
        self._preview_play_start_frame = 1
        self._preview_play_start_time = 0.0
        self._preview_request_id = 0
        self._preview_render_pending = False
        self._last_preview_render_time = 0.0
        self.undo_stack = []
        self.redo_stack = []
        self._undo_limit = 80
        self._typing_undo_row = None
        self._typing_undo_original = None
        self._waveform_undo_pushed = False

        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<space>", self.toggle_preview_playback)
        self.bind_all("<Left>", lambda event: self.step_playhead(-1, event))
        self.bind_all("<Right>", lambda event: self.step_playhead(1, event))
        self.bind_all("<Control-z>", self.undo_action)
        self.bind_all("<Control-y>", self.redo_action)
        self.bind_all("<Up>", lambda event: self.step_dialogue(-1, event))
        self.bind_all("<Down>", lambda event: self.step_dialogue(1, event))
        self.bind_all("<Return>", self.play_current_sentence)
        self.bind_all("<Delete>", self.delete_selected_dialogue)
        self.bind_all("<bracketleft>", lambda event: self.nudge_dialogue_edge("start", -0.05, event))
        self.bind_all("<bracketright>", lambda event: self.nudge_dialogue_edge("end", 0.05, event))
        self.bind_all("<Shift-bracketleft>", lambda event: self.nudge_dialogue_edge("start", 0.05, event))
        self.bind_all("<Shift-bracketright>", lambda event: self.nudge_dialogue_edge("end", -0.05, event))
        self.check_queue()

    def setup_ui(self):
        self.geometry("1500x860")
        self.minsize(1180, 720)
        self.script_row_widgets = {}
        self._script_row_loading = False
        self._log_expanded = False

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(14, weight=1)

        ctk.CTkLabel(sidebar, text="影片對話 HUD", font=("Microsoft JhengHei UI", 20, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 2))
        ctk.CTkLabel(sidebar, text="校稿工作台", text_color="#AAB0C0", anchor="w").grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))

        self.btn_video = ctk.CTkButton(sidebar, text="1 選擇影片", command=self.select_video, height=34)
        self.btn_video.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        self.btn_draw_people = ctk.CTkButton(sidebar, text="2 框選人物", command=self.start_person_box_mode, height=34, state="disabled")
        self.btn_draw_people.grid(row=3, column=0, sticky="ew", padx=12, pady=4)

        person_tools = ctk.CTkFrame(sidebar, fg_color="transparent")
        person_tools.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 4))
        person_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_confirm_people = ctk.CTkButton(person_tools, text="確認", command=self.confirm_people_count, height=30, state="disabled")
        self.btn_confirm_people.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_clear_people = ctk.CTkButton(person_tools, text="清除", command=self.clear_person_boxes, height=30, state="disabled", fg_color="#6B7280", hover_color="#7B8494")
        self.btn_clear_people.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.btn_speech = ctk.CTkButton(sidebar, text="3 辨識聲音", command=self.generate_speech_script, height=34, state="disabled", fg_color="#B94A48", hover_color="#D15A57")
        self.btn_speech.grid(row=5, column=0, sticky="ew", padx=12, pady=4)
        self.btn_data = ctk.CTkButton(sidebar, text="載入既有腳本", command=self.load_data, height=32, state="disabled")
        self.btn_data.grid(row=6, column=0, sticky="ew", padx=12, pady=4)
        self.btn_scan = ctk.CTkButton(sidebar, text="4 掃描對應", command=self.start_preview_scan, height=34, state="disabled")
        self.btn_scan.grid(row=7, column=0, sticky="ew", padx=12, pady=4)
        self.btn_export = ctk.CTkButton(sidebar, text="5 匯出影片", command=self.start_export, height=34, state="disabled", fg_color="#2E8B57", hover_color="#35A568")
        self.btn_export.grid(row=8, column=0, sticky="ew", padx=12, pady=4)

        self.progress_bar = ctk.CTkProgressBar(sidebar)
        self.progress_bar.grid(row=9, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.progress_bar.set(0)
        self.status_label = ctk.CTkLabel(sidebar, text="尚未選擇影片", anchor="w", justify="left", wraplength=190)
        self.status_label.grid(row=10, column=0, sticky="ew", padx=12, pady=(0, 8))

        settings = ctk.CTkFrame(sidebar)
        settings.grid(row=11, column=0, sticky="ew", padx=12, pady=(4, 8))
        settings.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(settings, text="辨識", anchor="w").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.whisper_model_var = ctk.StringVar(value="medium")
        self.whisper_menu = ctk.CTkOptionMenu(settings, values=["base", "small", "medium", "large-v3"], variable=self.whisper_model_var, height=28, state="disabled")
        self.whisper_menu.grid(row=0, column=1, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkLabel(settings, text="字級", anchor="w").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.slider_font_size = ctk.CTkSlider(settings, from_=18, to=180, command=self.update_style)
        self.slider_font_size.set(72)
        self.slider_font_size.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ctk.CTkLabel(settings, text="樣式", anchor="w").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.style_var = ctk.StringVar(value="classic")
        self.style_menu = ctk.CTkOptionMenu(settings, values=["classic", "oval", "capsule", "tech", "sharp"], variable=self.style_var, command=lambda _: self.update_settings(), height=28)
        self.style_menu.grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        ctk.CTkLabel(settings, text="無講話", anchor="w").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        self.silence_slider = ctk.CTkSlider(settings, from_=0.2, to=1.5, number_of_steps=13, variable=self.silence_seconds_var)
        self.silence_slider.grid(row=3, column=1, sticky="ew", padx=8, pady=4)
        self.lbl_silence = ctk.CTkLabel(settings, text="0.45s", width=52)
        self.lbl_silence.grid(row=4, column=1, sticky="w", padx=8, pady=(0, 8))
        self.silence_slider.configure(command=lambda value: self.lbl_silence.configure(text=f"{float(value):.2f}s"))
        self.audio_scrub_check = ctk.CTkCheckBox(settings, text="聲波定位播聲音", variable=self.audio_scrub_var)
        self.audio_scrub_check.grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        self.btn_toggle_log = ctk.CTkButton(sidebar, text="顯示記錄", command=self.toggle_log_panel, height=30, fg_color="#4B5563", hover_color="#5B6473")
        self.btn_toggle_log.grid(row=12, column=0, sticky="ew", padx=12, pady=(2, 4))
        self.log_box = ctk.CTkTextbox(sidebar, wrap="word", height=160)

        main = ctk.CTkFrame(self)
        main.grid(row=0, column=1, sticky="nsew", padx=6, pady=10)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(2, weight=0)

        controls = ctk.CTkFrame(main)
        controls.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        controls.grid_columnconfigure(2, weight=1)

        self.entry_id = ctk.CTkEntry(controls, width=1)
        self.entry_id.insert(0, "1")
        self.entry_speaker = ctk.CTkEntry(controls, width=1)
        self.entry_text = ctk.CTkEntry(controls, width=1)
        self.current_sentence_label = ctk.CTkLabel(
            controls,
            text="在右側腳本列表修改文字與說話者",
            anchor="w",
            text_color="#AAB0C0",
        )
        self.current_sentence_label.grid(row=0, column=0, columnspan=3, padx=(10, 8), pady=8, sticky="ew")
        self.btn_split_sentence = ctk.CTkButton(controls, text="斷句", width=64, command=self.split_current_sentence)
        self.btn_split_sentence.grid(row=0, column=3, padx=4, pady=8)
        self.btn_add_sentence = ctk.CTkButton(controls, text="新增", width=64, command=self.add_sentence_at_current_time)
        self.btn_add_sentence.grid(row=0, column=4, padx=4, pady=8)
        self.btn_undo = ctk.CTkButton(controls, text="Undo", width=62, command=self.undo_action)
        self.btn_undo.grid(row=0, column=5, padx=(10, 4), pady=8)
        self.btn_redo = ctk.CTkButton(controls, text="Redo", width=62, command=self.redo_action)
        self.btn_redo.grid(row=0, column=6, padx=(4, 10), pady=8)

        canvas_frame = ctk.CTkFrame(main, fg_color="#070A10")
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.preview_canvas = tk.Canvas(canvas_frame, bg="#070A10", highlightthickness=0, cursor="crosshair", takefocus=1)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.create_text(420, 240, text="選擇影片後會顯示預覽", fill="#687084", font=("Microsoft JhengHei UI", 16))
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_scroll)
        self.preview_canvas.bind("<ButtonPress-1>", self._on_canvas_drag_start)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.preview_canvas.bind("<ButtonPress-3>", self._on_canvas_right_click)
        self.preview_canvas.bind("<Motion>", self._on_canvas_motion)

        tool_row = ctk.CTkFrame(main)
        tool_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        tool_row.grid_columnconfigure(1, weight=1)
        self.lbl_timecode = ctk.CTkLabel(tool_row, text="00:00", width=70, font=("Consolas", 15, "bold"), text_color="#43E2A8")
        self.lbl_timecode.grid(row=0, column=0, sticky="w", padx=(8, 8), pady=(8, 4))
        self.slider_timeline = ctk.CTkSlider(tool_row, from_=1, to=1, command=self.on_timeline_scrub, state="disabled")
        self.slider_timeline.grid(row=0, column=1, sticky="ew", padx=4, pady=(8, 4))
        self.btn_keyframe = ctk.CTkButton(tool_row, text="目前框補位", width=96, command=self.use_current_boxes_as_rois)
        self.btn_keyframe.grid(row=0, column=2, sticky="e", padx=(4, 8), pady=(8, 4))
        self.waveform_canvas = tk.Canvas(tool_row, height=128, bg="#111827", highlightthickness=0)
        self.waveform_canvas.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 8))
        self.waveform_canvas.bind("<Button-1>", self.on_waveform_click)
        self.waveform_canvas.bind("<B1-Motion>", self.on_waveform_drag)
        self.waveform_canvas.bind("<ButtonRelease-1>", self.on_waveform_release)
        self.waveform_canvas.bind("<Button-2>", self.on_waveform_pan_start)
        self.waveform_canvas.bind("<B2-Motion>", self.on_waveform_pan_drag)
        self.waveform_canvas.bind("<ButtonRelease-2>", self.on_waveform_pan_release)
        self.waveform_canvas.bind("<Motion>", self.on_waveform_motion)
        self.waveform_canvas.bind("<MouseWheel>", self.on_waveform_zoom)

        script_panel = ctk.CTkFrame(self, width=390)
        script_panel.grid(row=0, column=2, sticky="nsew", padx=(6, 10), pady=10)
        script_panel.grid_propagate(False)
        script_panel.grid_columnconfigure(0, weight=1)
        script_panel.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(script_panel, text="腳本校稿", font=("Microsoft JhengHei UI", 18, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        script_tools = ctk.CTkFrame(script_panel, fg_color="transparent")
        script_tools.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        script_tools.grid_columnconfigure((0, 1, 2), weight=1)
        self.btn_play_sentence = ctk.CTkButton(script_tools, text="播放本句", command=self.play_current_sentence, height=30)
        self.btn_play_sentence.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_delete_sentence = ctk.CTkButton(script_tools, text="刪句", command=self.delete_selected_dialogue, height=30, fg_color="#8A3A3A", hover_color="#A64848")
        self.btn_delete_sentence.grid(row=0, column=1, sticky="ew", padx=4)
        self.btn_merge_sentence = ctk.CTkButton(script_tools, text="合併", command=self.merge_selected_dialogue, height=30)
        self.btn_merge_sentence.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        self.script_scroll = ctk.CTkScrollableFrame(script_panel)
        self.script_scroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.refresh_script_panel()

        self.log("準備好了。先選影片，再框選要追蹤的人。")

    def toggle_log_panel(self):
        if self._log_expanded:
            self.log_box.grid_forget()
            self.btn_toggle_log.configure(text="顯示記錄")
            self._log_expanded = False
        else:
            self.log_box.grid(row=14, column=0, sticky="nsew", padx=12, pady=(4, 12))
            self.btn_toggle_log.configure(text="隱藏記錄")
            self._log_expanded = True

    def refresh_script_panel(self):
        if not hasattr(self, "script_scroll"):
            return
        for child in self.script_scroll.winfo_children():
            child.destroy()
        self.script_row_widgets = {}
        dp = self.renderer.data_processor
        if not dp.has_data():
            ctk.CTkLabel(
                self.script_scroll,
                text="尚未建立腳本",
                text_color="#8A93A6",
                anchor="w",
            ).pack(fill="x", padx=8, pady=10)
            return
        time_col, speaker_col, text_col = dp.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            ctk.CTkLabel(self.script_scroll, text="腳本欄位不足", text_color="#FCA5A5").pack(fill="x", padx=8, pady=10)
            return

        speakers = self.get_person_speaker_options()
        self._script_row_loading = True
        for row_idx, row in dp.df.iterrows():
            speaker = "" if pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
            text = "" if pd.isna(row[text_col]) else str(row[text_col]).strip()
            time_text = "" if pd.isna(row[time_col]) else str(row[time_col]).strip()
            is_selected = row_idx == self.selected_dialogue_row
            is_silence = speaker == SILENCE_SPEAKER
            bg = "#28364A" if is_selected else ("#252A34" if is_silence else "#1B2230")
            line = ctk.CTkFrame(self.script_scroll, fg_color=bg, border_width=1 if is_selected else 0, border_color="#FBBF24")
            line.pack(fill="x", padx=4, pady=3)
            line.grid_columnconfigure(1, weight=1)

            time_btn = ctk.CTkButton(
                line,
                text=time_text or "--:--",
                width=98,
                height=28,
                fg_color="#334155",
                hover_color="#475569",
                command=lambda idx=row_idx: self.select_dialogue_row(idx, seek=True),
            )
            time_btn.grid(row=0, column=0, padx=(6, 4), pady=(6, 2), sticky="w")

            speaker_var = ctk.StringVar(value=speaker if speaker in speakers else (speaker or speakers[0]))
            speaker_menu = ctk.CTkOptionMenu(
                line,
                values=speakers,
                variable=speaker_var,
                width=112,
                height=28,
                command=lambda value, idx=row_idx: self.change_script_row_speaker(idx, value),
            )
            speaker_menu.grid(row=0, column=1, padx=4, pady=(6, 2), sticky="ew")

            ops = ctk.CTkFrame(line, fg_color="transparent")
            ops.grid(row=0, column=2, padx=(4, 6), pady=(6, 2), sticky="e")
            ctk.CTkButton(ops, text="▶", width=32, height=28, command=lambda idx=row_idx: self.play_dialogue_row(idx)).pack(side="left", padx=1)
            ctk.CTkButton(ops, text="合", width=32, height=28, command=lambda idx=row_idx: self.merge_dialogue_from_panel(idx)).pack(side="left", padx=1)
            ctk.CTkButton(ops, text="刪", width=32, height=28, fg_color="#8A3A3A", hover_color="#A64848", command=lambda idx=row_idx: self.delete_dialogue_from_panel(idx)).pack(side="left", padx=1)

            text_entry = ctk.CTkEntry(line)
            text_entry.insert(0, text)
            text_entry.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(2, 6))
            text_entry.bind("<FocusIn>", lambda _event, idx=row_idx: self.select_dialogue_row(idx, seek=False))
            text_entry.bind("<KeyRelease>", lambda _event, idx=row_idx, entry=text_entry: self.update_script_row_text(idx, entry.get()))
            line.bind("<Button-1>", lambda _event, idx=row_idx: self.select_dialogue_row(idx, seek=True))

            self.script_row_widgets[row_idx] = {"frame": line, "text": text_entry, "speaker": speaker_var}
        self._script_row_loading = False
        self.update_script_selection_styles()

    def update_script_selection_styles(self):
        if not hasattr(self, "script_row_widgets"):
            return
        dp = self.renderer.data_processor
        time_col, speaker_col, _ = dp.get_columns() if dp.has_data() else (None, None, None)
        for row_idx, widgets in self.script_row_widgets.items():
            frame = widgets.get("frame")
            if frame is None or not frame.winfo_exists():
                continue
            is_selected = row_idx == self.selected_dialogue_row
            speaker = ""
            if speaker_col is not None and dp.has_data() and row_idx in dp.df.index:
                value = dp.df.at[row_idx, speaker_col]
                speaker = "" if pd.isna(value) else str(value).strip()
            is_silence = speaker == SILENCE_SPEAKER
            bg = "#28364A" if is_selected else ("#252A34" if is_silence else "#1B2230")
            try:
                frame.configure(fg_color=bg, border_width=1 if is_selected else 0, border_color="#FBBF24")
            except Exception:
                frame.configure(fg_color=bg)

    def update_current_sentence_label(self):
        if not hasattr(self, "current_sentence_label"):
            return
        dp = self.renderer.data_processor
        if self.selected_dialogue_row is None or not dp.has_data() or self.selected_dialogue_row not in dp.df.index:
            self.current_sentence_label.configure(text="在右側腳本列表修改文字與說話者")
            return
        time_col, _, _ = dp.get_columns()
        speaker, text = dp.get_dialogue_row_values(self.selected_dialogue_row)
        time_text = ""
        if time_col is not None:
            value = dp.df.at[self.selected_dialogue_row, time_col]
            time_text = "" if pd.isna(value) else str(value).strip()
        preview = text.replace("\n", " ").strip()
        if len(preview) > 28:
            preview = preview[:28] + "..."
        self.current_sentence_label.configure(text=f"{time_text}  {speaker}  {preview}".strip())

    def selected_script_text_widget(self):
        widgets = getattr(self, "script_row_widgets", {}).get(self.selected_dialogue_row)
        if not widgets:
            return None
        entry = widgets.get("text")
        if entry is not None and entry.winfo_exists():
            return entry
        return None

    def current_dialogue_text_and_cursor(self):
        entry = self.selected_script_text_widget()
        if entry is not None:
            try:
                return entry.get(), entry.index("insert")
            except Exception:
                return entry.get(), len(entry.get()) // 2
        text = self.entry_text.get()
        try:
            return text, self.entry_text.index("insert")
        except Exception:
            return text, len(text) // 2

    def select_dialogue_row(self, row_idx, seek=True):
        dp = self.renderer.data_processor
        if not dp.has_data() or row_idx is None or row_idx not in dp.df.index:
            return
        time_col, _, _ = dp.get_columns()
        start, _ = parse_time_range(dp.df.at[row_idx, time_col]) if time_col is not None else (None, None)
        self.selected_dialogue_row = row_idx
        speaker, text = dp.get_dialogue_row_values(row_idx)
        matched_tid = next((tid for tid, name in self.renderer.yolo_id_to_speaker.items() if name == speaker), None)
        self._loading_person_fields = True
        if matched_tid is not None:
            self.entry_id.delete(0, "end")
            self.entry_id.insert(0, str(matched_tid))
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, speaker)
        self.entry_text.delete(0, "end")
        self.entry_text.insert(0, text)
        self._loading_person_fields = False
        self.update_current_sentence_label()
        if seek and start is not None and self.renderer.total_frames:
            frame = seconds_to_frame(start, self.renderer.fps, self.renderer.total_frames)
            self.stop_preview_playback()
            if self.slider_timeline.cget("state") == "normal":
                self.slider_timeline.set(frame)
            self.update_timecode_and_waveform(frame)
            self._render_scrub(frame)
        else:
            self.draw_waveform(self.current_frame())
        self.update_script_selection_styles()

    def change_script_row_speaker(self, row_idx, speaker):
        if self._script_row_loading:
            return
        dp = self.renderer.data_processor
        if not dp.has_data() or row_idx not in dp.df.index:
            return
        current, _ = dp.get_dialogue_row_values(row_idx)
        if current == speaker:
            return
        self.push_undo_state("腳本改說話者")
        if dp.update_dialogue_speaker(row_idx, speaker):
            self.selected_dialogue_row = row_idx
            self.renderer.bubble_cache.clear()
            self.select_dialogue_row(row_idx, seek=False)
            self.update_script_selection_styles()
            self.refresh_current_preview()

    def update_script_row_text(self, row_idx, text):
        if self._script_row_loading:
            return
        dp = self.renderer.data_processor
        if not dp.has_data() or row_idx not in dp.df.index:
            return
        _, old_text = dp.get_dialogue_row_values(row_idx)
        if old_text == text:
            return
        if self._typing_undo_row != row_idx:
            self._typing_undo_row = row_idx
            self._typing_undo_original = old_text
        if self._typing_undo_original is not None:
            self.push_undo_state("腳本文字")
            self._typing_undo_original = None
        if dp.update_dialogue_row(row_idx, text):
            self.selected_dialogue_row = row_idx
            self.renderer.bubble_cache.clear()
            self._loading_person_fields = True
            self.entry_text.delete(0, "end")
            self.entry_text.insert(0, text)
            self._loading_person_fields = False
            self.draw_waveform(self.current_frame())
            self.update_script_selection_styles()
            self.update_current_sentence_label()
            self.refresh_current_preview()

    def delete_dialogue_from_panel(self, row_idx):
        self.selected_dialogue_row = row_idx
        self.delete_selected_dialogue()

    def merge_dialogue_from_panel(self, row_idx):
        self.selected_dialogue_row = row_idx
        self.merge_selected_dialogue()

    def play_dialogue_row(self, row_idx):
        self.select_dialogue_row(row_idx, seek=True)
        self.play_current_sentence()

    def snapshot_state(self, label=""):
        dp = self.renderer.data_processor
        return {
            "label": label,
            "df": None if dp.df is None else dp.df.copy(deep=True),
            "df_path": dp.path,
            "cut_ranges": list(self.renderer.cut_ranges),
            "speakers": dict(self.renderer.yolo_id_to_speaker),
            "bubble_offsets": dict(self.renderer.bubble_offsets),
            "selected_row": self.selected_dialogue_row,
        }

    def push_undo_state(self, label=""):
        self.undo_stack.append(self.snapshot_state(label))
        if len(self.undo_stack) > self._undo_limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_state(self, state):
        dp = self.renderer.data_processor
        dp.df = None if state["df"] is None else state["df"].copy(deep=True)
        dp.path = state.get("df_path")
        self.renderer.set_cut_ranges(state.get("cut_ranges", []))
        self.renderer.yolo_id_to_speaker = dict(state.get("speakers", {}))
        self.renderer.bubble_offsets = dict(state.get("bubble_offsets", {}))
        self.selected_dialogue_row = state.get("selected_row")
        self.renderer.bubble_cache.clear()
        self.end_text_undo_group()
        self.refresh_after_state_restore()

    def refresh_after_state_restore(self):
        self.btn_scan.configure(state="normal" if self.people_count_confirmed and self.renderer.data_processor.has_data() else "disabled")
        self.refresh_script_panel()
        if self.slider_timeline.cget("state") == "normal":
            frame = self.current_frame()
            self.sync_fields_for_frame(frame)
            self.refresh_current_preview()
            self.draw_waveform(frame)

    def undo_action(self, event=None):
        if not self.undo_stack:
            return "break"
        self.redo_stack.append(self.snapshot_state("redo"))
        state = self.undo_stack.pop()
        self.restore_state(state)
        self.log(f"Undo: {state.get('label') or '回復上一個修改'}")
        return "break"

    def redo_action(self, event=None):
        if not self.redo_stack:
            return "break"
        self.undo_stack.append(self.snapshot_state("undo"))
        state = self.redo_stack.pop()
        self.restore_state(state)
        self.log(f"Redo: {state.get('label') or '重做修改'}")
        return "break"

    def begin_text_undo_group(self, event=None):
        if self.selected_dialogue_row is None:
            return
        self._typing_undo_row = self.selected_dialogue_row
        self._typing_undo_original = self.entry_text.get()

    def end_text_undo_group(self, event=None):
        self._typing_undo_row = None
        self._typing_undo_original = None

    def toggle_preview_playback(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        if self.slider_timeline.cget("state") != "normal":
            return "break"
        if self.preview_playing:
            self.stop_preview_playback()
        else:
            self.start_preview_playback()
        return "break"

    def start_preview_playback(self):
        if self.preview_playing:
            return
        self.preview_playing = True
        self._preview_play_start_frame = int(float(self.slider_timeline.get()))
        self.start_preview_audio()
        self._preview_play_start_time = time.perf_counter()
        self._play_preview_step()

    def stop_preview_playback(self):
        self.preview_playing = False
        if self._preview_play_after_id is not None:
            try:
                self.after_cancel(self._preview_play_after_id)
            except Exception:
                pass
            self._preview_play_after_id = None
        self.stop_audio_preview()

    def _play_preview_step(self):
        if not self.preview_playing:
            return
        total = max(1, int(self.renderer.total_frames or self._preview_play_start_frame))
        elapsed = time.perf_counter() - self._preview_play_start_time
        frame_idx = self._preview_play_start_frame + int(elapsed * max(self.renderer.fps or 30, 1))
        frame_idx = max(1, min(total, frame_idx))
        if frame_idx >= total:
            self.stop_preview_playback()
            return
        self.slider_timeline.set(frame_idx)
        self.update_timecode_and_waveform(frame_idx)
        self.sync_fields_for_frame(frame_idx)
        now = time.perf_counter()
        render_fps = min(max(self.renderer.fps or 30, 1), 18)
        if not self._preview_render_pending and now - self._last_preview_render_time >= 1.0 / render_fps:
            self._last_preview_render_time = now
            self._render_scrub(frame_idx)
        delay_ms = max(15, int(1000 / min(max(self.renderer.fps or 30, 1), 30)))
        self._preview_play_after_id = self.after(delay_ms, self._play_preview_step)

    def start_preview_audio(self):
        if not self.renderer.video_path or not self.renderer.fps:
            return False
        ffplay = shutil.which("ffplay")
        if not ffplay:
            self.log("找不到 ffplay，預覽播放只有畫面沒有聲音。")
            return False
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            frame_idx = 1
        seconds = frame_to_seconds(frame_idx, self.renderer.fps)
        self.stop_audio_preview()
        cmd = [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            "-ss", f"{seconds:.2f}",
            self._audio_preview_source(),
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            self._ffplay_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
            )
            return True
        except Exception:
            self._ffplay_process = None
            return False

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.status_label.configure(text=text)

    def check_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                if msg["type"] == "progress":
                    self.progress_bar.set(msg["value"])
                elif msg["type"] == "scan_finished":
                    self.on_scan_finished()
                elif msg["type"] == "finished":
                    self.on_export_finished(msg["out_path"])
                elif msg["type"] == "preview":
                    if msg.get("request_id") != self._preview_request_id:
                        continue
                    self._preview_render_pending = False
                    self.set_preview_image(Image.fromarray(msg["img"]), reset_view=False)
                    self.preview_boxes = msg.get("boxes", [])
                elif msg["type"] == "preview_done":
                    if msg.get("request_id") == self._preview_request_id:
                        self._preview_render_pending = False
                elif msg["type"] == "speech_done":
                    self.on_speech_done(msg["rows"], msg["out_csv"])
                elif msg["type"] == "error":
                    self.on_worker_error(msg["text"])
                elif msg["type"] == "error_log":
                    self.log(msg["text"])
                elif msg["type"] == "waveform":
                    self.waveform_samples = msg["samples"]
                    self.waveform_duration = msg.get("duration")
                    self.waveform_step_seconds = msg.get("step_seconds", self.waveform_step_seconds)
                    self.waveform_activity_intervals = msg.get("activity_intervals", [])
                    self._waveform_audio_path = msg.get("audio_path")
                    self.draw_waveform()
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def handle_renderer_update(self, msg_type, value, preview_img=None, out_path=None):
        if msg_type == "progress":
            self.ui_queue.put({"type": "progress", "value": value})
        elif msg_type == "scan_finished":
            self.ui_queue.put({"type": "scan_finished"})
        elif msg_type == "finished":
            self.ui_queue.put({"type": "finished", "out_path": out_path})
        elif msg_type == "error_log":
            self.ui_queue.put({"type": "error_log", "text": value})

    def update_settings(self):
        try:
            tid = int(self.entry_id.get())
        except ValueError:
            return
        if self._loading_person_fields:
            return
        self.renderer.settings["bubble_style"] = self.style_var.get()
        self.renderer.settings["bubble_pos"] = "auto"
        speaker = self.entry_speaker.get().strip()
        if speaker:
            self.renderer.yolo_id_to_speaker[tid] = speaker
            if self.selected_dialogue_row is not None:
                current_speaker, _ = self.renderer.data_processor.get_dialogue_row_values(self.selected_dialogue_row)
                if current_speaker != speaker:
                    self.push_undo_state("修改說話者")
                self.renderer.data_processor.update_dialogue_speaker(self.selected_dialogue_row, speaker)
        self.renderer.bubble_cache.clear()
        if self.slider_timeline.cget("state") == "normal":
            self.refresh_current_preview()

    def on_id_changed(self):
        if self._loading_person_fields:
            return
        try:
            tid = int(self.entry_id.get())
        except ValueError:
            return
        if tid <= 0:
            return
        self._loading_person_fields = True
        speaker = self.renderer.yolo_id_to_speaker.get(tid, f"人物 {tid}")
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, speaker)
        self._loading_person_fields = False
        if self.slider_timeline.cget("state") == "normal":
            try:
                frame_idx = int(float(self.slider_timeline.get()))
            except Exception:
                frame_idx = 1
            self.sync_fields_for_frame(frame_idx, strict_current_id=True)

    def update_dialogue_text(self):
        if self._loading_person_fields:
            return
        if self.selected_dialogue_row is None:
            return
        text = self.entry_text.get()
        if self._typing_undo_row != self.selected_dialogue_row:
            self.begin_text_undo_group()
        if self._typing_undo_original is not None and text != self._typing_undo_original:
            self.push_undo_state("修改文字")
            self._typing_undo_original = None
        if self.renderer.data_processor.update_dialogue_row(self.selected_dialogue_row, text):
            self.renderer.bubble_cache.clear()
            row_widgets = getattr(self, "script_row_widgets", {}).get(self.selected_dialogue_row)
            if row_widgets:
                script_entry = row_widgets.get("text")
                if script_entry is not None and script_entry.winfo_exists() and script_entry.get() != text:
                    self._script_row_loading = True
                    script_entry.delete(0, "end")
                    script_entry.insert(0, text)
                    self._script_row_loading = False
            if self.slider_timeline.cget("state") == "normal":
                self.refresh_current_preview()

    def split_current_sentence(self):
        if self.selected_dialogue_row is None:
            messagebox.showinfo(APP_TITLE, "請先點選一個有對話的泡泡或人物框。")
            return
        text = self.entry_text.get()
        if len(text.strip()) < 2:
            messagebox.showinfo(APP_TITLE, "這句太短，無法斷句。")
            return
        try:
            cursor_pos = self.entry_text.index("insert")
        except Exception:
            cursor_pos = len(text) // 2
        self.push_undo_state("切斷句")
        success, message, new_row_idx = self.renderer.data_processor.split_dialogue_row(self.selected_dialogue_row, cursor_pos)
        self.log(message)
        if not success:
            messagebox.showinfo(APP_TITLE, message)
            return
        self.renderer.bubble_cache.clear()
        self.selected_dialogue_row = new_row_idx
        self.refresh_script_panel()
        if self.slider_timeline.cget("state") == "normal":
            self.refresh_current_preview()
        self.select_person(int(self.entry_id.get()))

    def add_sentence_at_current_time(self):
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            frame_idx = 1
        start = frame_to_seconds(frame_idx, self.renderer.fps)
        end = min(start + 2.0, self.get_video_duration() or (start + 2.0))
        speaker = self.entry_speaker.get().strip() or self.renderer.yolo_id_to_speaker.get(1, "人物 1")
        text = self.entry_text.get().strip() or "新增對話"
        self.push_undo_state("新增句")
        row_idx = self.renderer.data_processor.insert_dialogue_row(start, end, speaker, text)
        self.selected_dialogue_row = row_idx
        self.renderer.bubble_cache.clear()
        self.btn_scan.configure(state="normal" if self.people_count_confirmed else "disabled")
        self.refresh_script_panel()
        self.log(f"已在 {format_timecode(start)} 新增一句。")
        if self.slider_timeline.cget("state") == "normal":
            self.slider_timeline.set(frame_idx)
            self.sync_fields_for_frame(frame_idx)
            self.refresh_current_preview()

    def _sync_selected_person_fields(self):
        try:
            tid = int(self.entry_id.get())
        except ValueError:
            return
        speaker = self.entry_speaker.get().strip()
        if speaker:
            self.renderer.yolo_id_to_speaker[tid] = speaker
            if self.selected_dialogue_row is not None:
                current_speaker, _ = self.renderer.data_processor.get_dialogue_row_values(self.selected_dialogue_row)
                if current_speaker != speaker:
                    self.push_undo_state("修改說話者")
                self.renderer.data_processor.update_dialogue_speaker(self.selected_dialogue_row, speaker)
        self.update_dialogue_text()
        self.renderer.bubble_cache.clear()

    def update_style(self, _event=None):
        self.renderer.style["font_size"] = int(self.slider_font_size.get())
        self.renderer.bubble_cache.clear()
        if self.slider_timeline.cget("state") == "normal":
            self.on_timeline_scrub(self.slider_timeline.get())

    def confirm_people_count(self):
        if not self.renderer.person_rois:
            messagebox.showinfo(APP_TITLE, "請先在預覽畫面框選至少一個人物。")
            return
        self.renderer.expected_people_count = len(self.renderer.person_rois)
        for idx in range(1, self.renderer.expected_people_count + 1):
            self.renderer.yolo_id_to_speaker.setdefault(idx, f"人物 {idx}")
        self.people_count_confirmed = True
        self.btn_speech.configure(state="normal")
        self.whisper_menu.configure(state="normal")
        self.btn_data.configure(state="normal")
        self.btn_scan.configure(state="normal" if self.renderer.data_processor.has_data() else "disabled")
        self.log(f"已確認 {self.renderer.expected_people_count} 個人物框。請命名人物，之後腳本選單會用這些名字。")
        self.open_speaker_mapper(list(range(1, self.renderer.expected_people_count + 1)))

    def mark_people_count_unconfirmed(self):
        if not self.renderer.video_path:
            return
        self.people_count_confirmed = False
        self.renderer.tracking_data = {}
        self.btn_speech.configure(state="disabled")
        self.whisper_menu.configure(state="disabled")
        self.btn_data.configure(state="disabled")
        self.btn_scan.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self.btn_confirm_people.configure(state="normal")
        self.log("人物框已變更，請重新確認後再繼續。")

    def start_person_box_mode(self):
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        self._canvas_mode = "person_roi"
        self.btn_draw_people.configure(text="拖曳框選中", fg_color="#B94A48")
        self.log("請在預覽畫面拖曳框住每一個要追蹤的人。每畫一框就是一個人。")

    def clear_person_boxes(self):
        self.renderer.person_rois = []
        self.preview_boxes = []
        self.people_count_confirmed = False
        self.renderer.tracking_data = {}
        self.btn_confirm_people.configure(state="normal" if self.renderer.video_path else "disabled")
        self.btn_clear_people.configure(state="disabled")
        self.btn_speech.configure(state="disabled")
        self.whisper_menu.configure(state="disabled")
        self.btn_data.configure(state="disabled")
        self.btn_scan.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self._refresh_canvas()
        self.log("已清除人物框，請重新框選。")

    def use_current_boxes_as_rois(self):
        if not self.preview_boxes:
            messagebox.showinfo(APP_TITLE, "目前畫面沒有可用的人物框。請先掃描或框選人物。")
            return
        rois = []
        for box in sorted(self.preview_boxes, key=lambda item: item["id"]):
            x1, y1, x2, y2 = box["bbox"]
            width = max(1, x2 - x1)
            height = max(1, y2 - y1)
            rois.append((
                max(0, int(x1 - width * 0.35)),
                max(0, int(y1 - height * 0.35)),
                int(x2 + width * 0.35),
                int(y2 + height * 2.2),
            ))
        self.renderer.person_rois = rois
        self.mark_people_count_unconfirmed()
        self.btn_clear_people.configure(state="normal")
        self._refresh_canvas()
        self.log(f"已用目前畫面更新 {len(rois)} 個人物框，請重新確認並掃描。")

    def select_video(self):
        self.stop_preview_playback()
        path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv")])
        if not path:
            return
        self.renderer.video_path = path
        self.renderer.data_processor = DataProcessor()
        self.renderer.tracking_data = {}
        self.renderer.set_cut_ranges([])
        self.renderer.person_rois = []
        self._clear_waveform_audio_cache()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.end_text_undo_group()
        self.selected_dialogue_row = None
        self.refresh_script_panel()
        self.waveform_samples = None
        self.waveform_duration = None
        self.waveform_step_seconds = 0.01
        self.waveform_activity_intervals = []
        self.waveform_view_start = 0.0
        self.waveform_view_end = None
        self.people_count_confirmed = False
        self.btn_export.configure(state="disabled")
        self.btn_scan.configure(state="disabled")
        self.btn_speech.configure(state="disabled")
        self.btn_data.configure(state="disabled")
        self.whisper_menu.configure(state="disabled")
        self.btn_draw_people.configure(state="normal")
        self.btn_confirm_people.configure(state="normal")
        self.btn_clear_people.configure(state="disabled")
        self.progress_bar.set(0)
        self.log(f"已選擇影片：{os.path.basename(path)}")

        safe_path = get_safe_path(path)
        cap = cv2.VideoCapture(safe_path)
        if not cap.isOpened():
            messagebox.showerror(APP_TITLE, "影片無法讀取。")
            return
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.renderer.fps = fps
        self.renderer.total_frames = total_frames
        auto_size = self.renderer.set_video_resolution(width, height)
        self.slider_font_size.set(auto_size)
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(30, max(0, total_frames - 1)))
        ret, frame = cap.read()
        cap.release()
        if ret:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.set_preview_image(Image.fromarray(self.renderer._resize_preview(rgb)), reset_view=True)
        self.log(f"影片資訊：{width}x{height}，{total_frames} frames。請框選要追蹤的人。")
        threading.Thread(target=self._generate_waveform, daemon=True).start()

    def load_data(self):
        if not self.people_count_confirmed:
            messagebox.showinfo(APP_TITLE, "請先框選人物並確認框選。")
            return
        path = filedialog.askopenfilename(filetypes=[("Dialogue Files", "*.csv *.xlsx *.xls")])
        if not path:
            return
        if self.renderer.data_processor.has_data():
            self.push_undo_state("載入腳本")
        success, message = self.renderer.data_processor.load_data(path)
        if success:
            added = self.renderer.data_processor.add_silence_rows(self.get_video_duration(), self.get_silence_seconds())
            if added:
                message += f"，已補 {added} 段無講話"
        self.log(message)
        if success:
            self.btn_scan.configure(state="normal")
            self.refresh_script_panel()
            speakers = self.renderer.data_processor.get_unique_speakers()
            if speakers:
                self.entry_speaker.delete(0, "end")
                self.entry_speaker.insert(0, speakers[0])
                self.log(f"找到說話者：{', '.join(speakers[:8])}")

    def get_video_duration(self):
        if self.renderer.total_frames and self.renderer.fps:
            return self.renderer.total_frames / max(self.renderer.fps, 1)
        return None

    def get_silence_seconds(self):
        try:
            return max(0.2, float(self.silence_seconds_var.get()))
        except Exception:
            return MIN_SILENCE_SECONDS

    def get_person_speaker_options(self):
        count = max(len(self.renderer.person_rois), self.renderer.expected_people_count, 1)
        options = []
        for idx in range(1, count + 1):
            options.append(self.renderer.yolo_id_to_speaker.get(idx, f"人物 {idx}"))
        unique = []
        for value in options:
            if value and value not in unique:
                unique.append(value)
        unique.append(SILENCE_SPEAKER)
        return unique

    def _generate_waveform(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not self.renderer.video_path:
            return
        self._clear_waveform_audio_cache()
        fd, wav_path = tempfile.mkstemp(suffix="_waveform.wav")
        os.close(fd)
        cmd = [
            ffmpeg, "-y", "-v", "error", "-i", get_safe_path(self.renderer.video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", wav_path
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, timeout=90)
            if result.returncode != 0 or not os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
                return
            raw = subprocess.check_output(
                [ffmpeg, "-v", "error", "-i", wav_path, "-f", "s16le", "-"],
                startupinfo=startupinfo,
                timeout=60,
            )
        except Exception:
            try:
                os.remove(wav_path)
            except OSError:
                pass
            return
        audio = np.frombuffer(raw, dtype=np.int16)
        if audio.size == 0:
            try:
                os.remove(wav_path)
            except OSError:
                pass
            return
        duration = audio.size / 16000.0
        sample_rate = 16000
        step_seconds = 0.01
        step = max(1, int(sample_rate * step_seconds))
        trimmed = audio[: step * (audio.size // step)]
        if trimmed.size == 0:
            return
        peaks = np.max(np.abs(trimmed.reshape(-1, step)), axis=1).astype(np.float32)
        max_peak = float(peaks.max()) or 1.0
        peaks = peaks / max_peak
        activity_intervals = self._activity_intervals_from_levels(peaks, step_seconds)
        self.ui_queue.put({
            "type": "waveform",
            "samples": peaks,
            "duration": duration,
            "step_seconds": step_seconds,
            "activity_intervals": activity_intervals,
            "audio_path": wav_path,
        })

    def _activity_intervals_from_levels(self, levels, step_seconds, min_active=0.08, bridge_gap=0.14):
        levels = np.asarray(levels, dtype=np.float32)
        if levels.size == 0:
            return []
        floor = float(np.percentile(levels, 35))
        peak = float(np.percentile(levels, 95))
        threshold = max(floor * 2.2, peak * 0.18, 0.035)
        active = levels >= threshold
        raw = []
        start = None
        for idx, is_active in enumerate(active.tolist()):
            if is_active and start is None:
                start = idx
            elif not is_active and start is not None:
                raw.append((start * step_seconds, idx * step_seconds))
                start = None
        if start is not None:
            raw.append((start * step_seconds, levels.size * step_seconds))

        merged = []
        for start, end in raw:
            if end - start < min_active:
                continue
            if merged and start - merged[-1][1] <= bridge_gap:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        return [(round(start, 3), round(end, 3)) for start, end in merged if end - start >= min_active]

    def get_waveform_timeline_duration(self):
        if self.renderer.total_frames and self.renderer.fps:
            return self.renderer.total_frames / max(self.renderer.fps, 1)
        if self.waveform_duration and self.waveform_duration > 0:
            return self.waveform_duration
        return 0.0

    def get_waveform_view_range(self):
        duration = max(self.get_waveform_timeline_duration(), 0.001)
        start = max(0.0, float(self.waveform_view_start or 0.0))
        end = self.waveform_view_end
        if end is None or end <= start:
            end = duration
        span = max(0.1, min(duration, float(end) - start))
        start = max(0.0, min(start, duration - span))
        end = start + span
        self.waveform_view_start = start
        self.waveform_view_end = end
        return start, end

    def seconds_to_waveform_x(self, seconds, width):
        view_start, view_end = self.get_waveform_view_range()
        return int(((seconds - view_start) / max(view_end - view_start, 0.001)) * width)

    def zoom_waveform_view(self, anchor_x, zoom_in):
        duration = self.get_waveform_timeline_duration()
        if duration <= 0:
            return
        w = max(1, self.waveform_canvas.winfo_width())
        view_start, view_end = self.get_waveform_view_range()
        span = view_end - view_start
        anchor_ratio = max(0.0, min(1.0, anchor_x / w))
        anchor_time = view_start + span * anchor_ratio
        factor = 0.75 if zoom_in else 1.35
        new_span = max(0.5, min(duration, span * factor))
        new_start = anchor_time - new_span * anchor_ratio
        new_start = max(0.0, min(duration - new_span, new_start))
        self.waveform_view_start = new_start
        self.waveform_view_end = new_start + new_span
        self.draw_waveform(self.current_frame())

    def pan_waveform_view(self, delta_x):
        duration = self.get_waveform_timeline_duration()
        if duration <= 0:
            return
        w = max(1, self.waveform_canvas.winfo_width())
        start, end = self._waveform_pan_start_range
        span = max(0.1, end - start)
        shift = -(delta_x / w) * span
        new_start = max(0.0, min(duration - span, start + shift))
        self.waveform_view_start = new_start
        self.waveform_view_end = new_start + span
        self.draw_waveform(self.current_frame())

    def current_frame(self):
        try:
            return int(float(self.slider_timeline.get()))
        except Exception:
            return 1

    def draw_waveform(self, playhead_frame=None):
        if not hasattr(self, "waveform_canvas"):
            return
        canvas = self.waveform_canvas
        canvas.delete("all")
        w = max(1, canvas.winfo_width() or 800)
        h = max(1, canvas.winfo_height() or 58)
        samples = self.waveform_samples
        if samples is None or len(samples) == 0:
            canvas.create_text(w // 2, h // 2, text="聲波載入中", fill="#6B7280")
            return
        self.waveform_dialogue_handles = []
        wave_top = 18
        mid = wave_top + (h - wave_top) // 2
        count = len(samples)
        view_start, view_end = self.get_waveform_view_range()
        view_span = max(view_end - view_start, 0.001)
        for x in range(w):
            seconds = view_start + (x / max(1, w - 1)) * view_span
            idx = int(seconds / max(self.waveform_step_seconds, 1e-6))
            if idx < 0 or idx >= count:
                continue
            amp = float(samples[idx]) * ((h - wave_top) * 0.42)
            canvas.create_line(x, mid - amp, x, mid + amp, fill="#38BDF8")
        self.draw_waveform_dialogue_labels(canvas, w, h)
        frame = playhead_frame
        if frame is None and self.slider_timeline.cget("state") == "normal":
            try:
                frame = int(float(self.slider_timeline.get()))
            except Exception:
                frame = None
        if frame and self.renderer.total_frames:
            seconds = frame_to_seconds(frame, self.renderer.fps)
            px = self.seconds_to_waveform_x(seconds, w)
            px = max(0, min(w, px))
            canvas.create_line(px, 0, px, h, fill="#FBBF24", width=2)

    def draw_waveform_dialogue_labels(self, canvas, width, height):
        dp = self.renderer.data_processor
        if not dp.has_data() or not self.renderer.total_frames or not self.renderer.fps:
            return
        time_col, speaker_col, text_col = dp.get_columns()
        if time_col is None or text_col is None:
            return
        last_x = -999
        for row_idx, row in dp.df.iterrows():
            speaker = "" if speaker_col is None or pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
            if speaker == SILENCE_SPEAKER:
                continue
            start, end = parse_time_range(row[time_col])
            if start is None or end is None or end <= start:
                continue
            text = "" if pd.isna(row[text_col]) else str(row[text_col]).strip().strip("「」")
            text = text.replace("\n", "").replace("\r", "")
            if not text:
                continue
            x = self.seconds_to_waveform_x(start, width)
            x2 = self.seconds_to_waveform_x(end, width)
            if x2 < 0 or x > width:
                continue
            visible_x = max(0, min(width, x))
            visible_x2 = max(visible_x + 1, min(width, x2))
            draw_x = min(visible_x2 - 1, visible_x + 1)
            draw_x2 = max(draw_x + 1, visible_x2 - 1)
            is_selected = row_idx == self.selected_dialogue_row
            palette = ["#243B53", "#3A2F57", "#284A3A", "#4A3A24", "#443044", "#24484A"]
            fill = "#6B4E16" if is_selected else palette[int(row_idx) % len(palette)]
            outline = "#FBBF24" if is_selected else "#53627A"
            width_px = 2 if is_selected else 1
            canvas.create_rectangle(draw_x, 18, draw_x2, height, fill=fill, stipple="gray25", outline="")
            canvas.create_rectangle(draw_x, 18, draw_x2, height, outline=outline, width=width_px)
            if 0 <= x <= width:
                canvas.create_rectangle(max(0, x - 4), 18, min(width, x + 4), height, fill="#A78BFA", outline="")
            if 0 <= x2 <= width:
                canvas.create_rectangle(max(0, x2 - 4), 18, min(width, x2 + 4), height, fill="#6D5DD3", outline="")
            self.waveform_dialogue_handles.append({
                "row_idx": row_idx,
                "start": start,
                "end": end,
                "x1": x,
                "x2": x2,
            })
            label_x = max(0, min(width - 1, x))
            if label_x - last_x < 28:
                continue
            last_x = label_x
            label = text[:3]
            label_color = "#FFF3B0" if is_selected else "#D6CCFF"
            canvas.create_text(label_x + 3, 4, anchor="nw", text=label, fill=label_color, font=("Microsoft JhengHei UI", 9, "bold" if is_selected else "normal"))

    def _frame_from_waveform_x(self, x):
        self.waveform_canvas.focus_set()
        if not self.renderer.total_frames:
            return None
        seconds = self._seconds_from_waveform_x(x)
        return seconds_to_frame(seconds, self.renderer.fps, self.renderer.total_frames)

    def _seconds_from_waveform_x(self, x):
        w = max(1, self.waveform_canvas.winfo_width())
        ratio = max(0.0, min(1.0, x / w))
        view_start, view_end = self.get_waveform_view_range()
        return view_start + ratio * max(view_end - view_start, 0.001)

    def _waveform_hit_time_handle(self, x, y):
        if y < 12:
            return None
        tolerance = 10
        best = None
        best_dist = tolerance + 1
        for item in self.waveform_dialogue_handles:
            for edge, px in (("start", item["x1"]), ("end", item["x2"])):
                dist = abs(x - px)
                if dist <= tolerance and dist < best_dist:
                    best_dist = dist
                    best = dict(item, edge=edge)
        return best

    def _waveform_hit_dialogue_range(self, x, y):
        if y < 18:
            return None
        for item in reversed(self.waveform_dialogue_handles):
            x1, x2 = sorted((item["x1"], item["x2"]))
            if x1 <= x <= x2:
                return dict(item, edge="range")
        return None

    def _neighbor_time_limits(self, row_idx):
        dp = self.renderer.data_processor
        if not dp.has_data():
            return 0.0, self.get_waveform_timeline_duration()
        time_col, speaker_col, _ = dp.get_columns()
        if time_col is None:
            return 0.0, self.get_waveform_timeline_duration()
        indices = list(dp.df.index)
        try:
            pos = indices.index(row_idx)
        except ValueError:
            return 0.0, self.get_waveform_timeline_duration()
        min_start = 0.0
        max_end = self.get_waveform_timeline_duration()
        for prev_pos in range(pos - 1, -1, -1):
            prev_idx = indices[prev_pos]
            speaker = "" if speaker_col is None or pd.isna(dp.df.at[prev_idx, speaker_col]) else str(dp.df.at[prev_idx, speaker_col]).strip()
            if speaker == SILENCE_SPEAKER:
                continue
            _, prev_end = parse_time_range(dp.df.at[prev_idx, time_col])
            if prev_end is not None:
                min_start = prev_end
            break
        for next_pos in range(pos + 1, len(indices)):
            next_idx = indices[next_pos]
            speaker = "" if speaker_col is None or pd.isna(dp.df.at[next_idx, speaker_col]) else str(dp.df.at[next_idx, speaker_col]).strip()
            if speaker == SILENCE_SPEAKER:
                continue
            next_start, _ = parse_time_range(dp.df.at[next_idx, time_col])
            if next_start is not None:
                max_end = next_start
            break
        return min_start, max_end

    def update_waveform_time_handle(self, x):
        handle = self.waveform_drag_handle
        if not handle:
            return None
        dp = self.renderer.data_processor
        time_col, _, _ = dp.get_columns()
        if time_col is None:
            return None
        row_idx = handle["row_idx"]
        start, end = parse_time_range(dp.df.at[row_idx, time_col])
        if start is None or end is None:
            return None
        min_start, max_end = self._neighbor_time_limits(row_idx)
        seconds = self._seconds_from_waveform_x(x)
        min_duration = 0.05
        if handle["edge"] == "start":
            start = max(min_start, min(seconds, end - min_duration))
            edge_seconds = start
        else:
            end = min(max_end, max(seconds, start + min_duration))
            edge_seconds = end
        if not dp.update_dialogue_time(row_idx, start, end, min_duration=min_duration):
            return None
        self.selected_dialogue_row = row_idx
        frame = seconds_to_frame(edge_seconds, self.renderer.fps, self.renderer.total_frames)
        self.slider_timeline.set(frame)
        self.update_timecode_and_waveform(frame)
        row_speaker, row_text = dp.get_dialogue_row_values(row_idx)
        matched_tid = next(
            (tid for tid, name in self.renderer.yolo_id_to_speaker.items() if name == row_speaker),
            None,
        )
        self._loading_person_fields = True
        if matched_tid is not None:
            self.entry_id.delete(0, "end")
            self.entry_id.insert(0, str(matched_tid))
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, row_speaker)
        self.entry_text.delete(0, "end")
        self.entry_text.insert(0, row_text)
        self._loading_person_fields = False
        self._render_scrub(frame)
        return frame

    def update_waveform_range_drag(self, x):
        handle = self.waveform_drag_handle
        start_state = self._waveform_range_drag_start
        if not handle or not start_state:
            return None
        dp = self.renderer.data_processor
        row_idx = handle["row_idx"]
        delta = self._seconds_from_waveform_x(x) - start_state["mouse_seconds"]
        min_start, max_end = self._neighbor_time_limits(row_idx)
        duration = start_state["end"] - start_state["start"]
        new_start = start_state["start"] + delta
        new_start = max(min_start, min(max_end - duration, new_start))
        new_end = new_start + duration
        if not dp.update_dialogue_time(row_idx, new_start, new_end):
            return None
        self.selected_dialogue_row = row_idx
        frame = seconds_to_frame(new_start, self.renderer.fps, self.renderer.total_frames)
        self.slider_timeline.set(frame)
        self.update_timecode_and_waveform(frame)
        self._render_scrub(frame)
        return frame

    def seek_to_frame(self, frame, play_sound=False):
        if frame is None or self.slider_timeline.cget("state") != "normal":
            return
        self.stop_preview_playback()
        frame = max(1, min(int(self.renderer.total_frames or frame), int(frame)))
        self.slider_timeline.set(frame)
        self.update_timecode_and_waveform(frame)
        self.sync_fields_for_frame(frame)
        self._render_scrub(frame)
        if play_sound and self.audio_scrub_var.get():
            self.play_audio_preview(frame, duration=0.35, force=True)

    def on_waveform_click(self, event):
        self._waveform_mouse_down = True
        self._waveform_drag_moved = False
        self._waveform_undo_pushed = False
        handle = self._waveform_hit_time_handle(event.x, event.y)
        if handle:
            self.stop_preview_playback()
            self.push_undo_state("調整句子時間")
            self._waveform_undo_pushed = True
            self.waveform_drag_handle = handle
            self._waveform_drag_mode = "handle"
            self.selected_dialogue_row = handle["row_idx"]
            self.waveform_canvas.configure(cursor="sb_h_double_arrow")
            frame = self.update_waveform_time_handle(event.x)
            if frame is not None and self.audio_scrub_var.get():
                self.play_audio_preview(frame, duration=0.25, force=True)
            return
        range_hit = self._waveform_hit_dialogue_range(event.x, event.y)
        if range_hit:
            self.stop_preview_playback()
            self.push_undo_state("移動句子時間")
            self._waveform_undo_pushed = True
            self.waveform_drag_handle = range_hit
            self._waveform_drag_mode = "range"
            self.selected_dialogue_row = range_hit["row_idx"]
            self._waveform_range_drag_start = {
                "mouse_seconds": self._seconds_from_waveform_x(event.x),
                "start": range_hit["start"],
                "end": range_hit["end"],
            }
            self.waveform_canvas.configure(cursor="fleur")
            self.seek_to_frame(seconds_to_frame(range_hit["start"], self.renderer.fps, self.renderer.total_frames), play_sound=False)
            return
        self._waveform_drag_mode = None
        self.seek_to_frame(self._frame_from_waveform_x(event.x), play_sound=False)

    def on_waveform_drag(self, event):
        if self.waveform_drag_handle:
            if self._waveform_drag_mode == "range":
                self.update_waveform_range_drag(event.x)
            else:
                self.update_waveform_time_handle(event.x)
            return

    def on_waveform_release(self, event):
        was_mouse_down = self._waveform_mouse_down
        self._waveform_mouse_down = False
        if not self.waveform_drag_handle:
            mode = self._waveform_drag_mode
            moved = self._waveform_drag_moved
            self._waveform_drag_mode = None
            if not was_mouse_down:
                return
            if mode == "pan" and not moved:
                frame = self._frame_from_waveform_x(event.x)
                self.seek_to_frame(frame, play_sound=bool(self.audio_scrub_var.get()))
            return
        if self._waveform_drag_mode == "range":
            frame = self.update_waveform_range_drag(event.x)
        else:
            frame = self.update_waveform_time_handle(event.x)
        self.waveform_drag_handle = None
        self._waveform_drag_mode = None
        self._waveform_range_drag_start = None
        self._waveform_undo_pushed = False
        self.waveform_canvas.configure(cursor="")
        self.renderer.bubble_cache.clear()
        self.refresh_script_panel()
        if frame is not None and self.audio_scrub_var.get():
            self.play_audio_preview(frame, duration=0.35, force=True)

    def on_waveform_motion(self, event):
        if self.waveform_drag_handle:
            self.waveform_canvas.configure(cursor="fleur" if self._waveform_drag_mode == "range" else "sb_h_double_arrow")
            return
        if self._waveform_hit_time_handle(event.x, event.y):
            self.waveform_canvas.configure(cursor="sb_h_double_arrow")
        elif self._waveform_hit_dialogue_range(event.x, event.y):
            self.waveform_canvas.configure(cursor="fleur")
        else:
            self.waveform_canvas.configure(cursor="")

    def on_waveform_pan_start(self, event):
        self.waveform_canvas.focus_set()
        self._waveform_pan_start_x = event.x
        self._waveform_pan_start_range = self.get_waveform_view_range()
        self.waveform_canvas.configure(cursor="fleur")

    def on_waveform_pan_drag(self, event):
        self.pan_waveform_view(event.x - self._waveform_pan_start_x)

    def on_waveform_pan_release(self, event):
        self.waveform_canvas.configure(cursor="")

    def on_waveform_zoom(self, event):
        self.waveform_canvas.focus_set()
        self.zoom_waveform_view(event.x, event.delta > 0)

    def step_playhead(self, delta, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        if self.slider_timeline.cget("state") != "normal":
            return "break"
        try:
            current = int(float(self.slider_timeline.get()))
        except Exception:
            current = 1
        self.seek_to_frame(current + int(delta), play_sound=True)
        return "break"

    def dialogue_indices(self):
        dp = self.renderer.data_processor
        if not dp.has_data():
            return []
        return list(dp.df.index)

    def step_dialogue(self, delta, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        indices = self.dialogue_indices()
        if not indices:
            return "break"
        if self.selected_dialogue_row in indices:
            pos = indices.index(self.selected_dialogue_row)
        else:
            pos = 0
        pos = max(0, min(len(indices) - 1, pos + int(delta)))
        self.select_dialogue_row(indices[pos], seek=True)
        return "break"

    def play_current_sentence(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        dp = self.renderer.data_processor
        if self.selected_dialogue_row is None or not dp.has_data():
            return "break"
        time_col, _, _ = dp.get_columns()
        if time_col is None or self.selected_dialogue_row not in dp.df.index:
            return "break"
        start, end = parse_time_range(dp.df.at[self.selected_dialogue_row, time_col])
        if start is None or end is None:
            return "break"
        frame = seconds_to_frame(start, self.renderer.fps, self.renderer.total_frames)
        self.seek_to_frame(frame, play_sound=False)
        self.play_audio_preview(frame, duration=max(0.15, end - start), force=True)
        return "break"

    def delete_selected_dialogue(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data() or row_idx not in dp.df.index:
            return "break"
        time_col, speaker_col, _ = dp.get_columns()
        start, end = parse_time_range(dp.df.at[row_idx, time_col]) if time_col is not None else (None, None)
        speaker = "" if speaker_col is None or pd.isna(dp.df.at[row_idx, speaker_col]) else str(dp.df.at[row_idx, speaker_col]).strip()
        self.push_undo_state("刪除句")
        if speaker == SILENCE_SPEAKER and start is not None and end is not None and end > start:
            self.renderer.set_cut_ranges(normalize_time_ranges(self.renderer.cut_ranges + [(start, end)]))
        if dp.delete_dialogue_row(row_idx):
            indices = self.dialogue_indices()
            self.selected_dialogue_row = indices[min(len(indices) - 1, max(0, row_idx))] if indices else None
            self.renderer.bubble_cache.clear()
            self.refresh_script_panel()
            self.refresh_current_preview()
        return "break"

    def merge_selected_dialogue(self):
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data():
            return
        self.push_undo_state("合併句")
        success, message = dp.merge_dialogue_rows(row_idx)
        self.log(message)
        if success:
            self.selected_dialogue_row = row_idx if row_idx in dp.df.index else None
            self.renderer.bubble_cache.clear()
            self.refresh_script_panel()
            self.select_dialogue_row(self.selected_dialogue_row, seek=True)

    def nudge_dialogue_edge(self, edge, delta, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data() or row_idx not in dp.df.index:
            return "break"
        time_col, _, _ = dp.get_columns()
        if time_col is None:
            return "break"
        start, end = parse_time_range(dp.df.at[row_idx, time_col])
        if start is None or end is None:
            return "break"
        if edge == "start":
            start = max(0.0, min(end - 0.05, start + float(delta)))
        else:
            end = max(start + 0.05, end + float(delta))
        self.push_undo_state("微調句子時間")
        if dp.update_dialogue_time(row_idx, start, end):
            self.selected_dialogue_row = row_idx
            self.refresh_script_panel()
            self.select_dialogue_row(row_idx, seek=False)
            self.refresh_current_preview()
        return "break"

    def generate_speech_script(self):
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        if not self.people_count_confirmed:
            messagebox.showinfo(APP_TITLE, "請先框選人物並確認框選。")
            return
        self.btn_speech.configure(state="disabled", text="辨識中...")
        self.btn_data.configure(state="disabled")
        self.whisper_menu.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始辨識聲音。會產生可編輯腳本，完成後再對人物。")
        threading.Thread(target=self._run_speech_task, daemon=True).start()

    def _run_speech_task(self):
        try:
            try:
                import torch
                torch_lib_dir = os.path.dirname(torch.__file__)
                nvidia_dir = os.path.join(os.path.dirname(torch_lib_dir), "nvidia")
                if os.path.exists(nvidia_dir):
                    for folder in os.listdir(nvidia_dir):
                        bin_path = os.path.join(nvidia_dir, folder, "bin")
                        if os.path.exists(bin_path) and bin_path not in os.environ.get("PATH", ""):
                            os.environ["PATH"] = bin_path + os.pathsep + os.environ["PATH"]
            except Exception:
                pass

            from faster_whisper import WhisperModel

            safe_path = get_safe_path(self.renderer.video_path)
            model_size = self.whisper_model_var.get()
            self.ui_queue.put({"type": "progress", "value": 0.05})
            model = WhisperModel(model_size, device="auto", compute_type="int8")
            try:
                segments, _info = model.transcribe(
                    safe_path,
                    beam_size=5,
                    language="zh",
                    vad_filter=True,
                    word_timestamps=True,
                    vad_parameters={"min_silence_duration_ms": int(self.get_silence_seconds() * 1000)},
                    condition_on_previous_text=False,
                )
                rows = self._segments_to_rows(
                    list(segments),
                    self.renderer.total_frames,
                    self.renderer.fps,
                    self.get_silence_seconds(),
                    safe_path,
                    model,
                )
            except RuntimeError as exc:
                if "cublas" not in str(exc).lower() and "cuda" not in str(exc).lower():
                    raise
                self.ui_queue.put({"type": "progress", "value": 0.1})
                self.ui_queue.put({"type": "error_log", "text": "CUDA 無法使用，已自動改用 CPU 辨識。"})
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
                segments, _info = model.transcribe(
                    safe_path,
                    beam_size=5,
                    language="zh",
                    vad_filter=True,
                    word_timestamps=True,
                    vad_parameters={"min_silence_duration_ms": int(self.get_silence_seconds() * 1000)},
                    condition_on_previous_text=False,
                )
                rows = self._segments_to_rows(
                    list(segments),
                    self.renderer.total_frames,
                    self.renderer.fps,
                    self.get_silence_seconds(),
                    safe_path,
                    model,
                )

            if not rows:
                self.ui_queue.put({"type": "error", "text": "沒有辨識到可用的語音內容。"})
                return

            base = os.path.splitext(self.renderer.video_path)[0]
            out_csv = available_output_path(base + "_dialogue.csv")
            pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8-sig")
            self.ui_queue.put({"type": "speech_done", "rows": rows, "out_csv": out_csv})
        except ModuleNotFoundError as exc:
            if exc.name == "faster_whisper":
                self.ui_queue.put({"type": "error", "text": "缺少 faster-whisper。請先安裝：pip install faster-whisper"})
            else:
                self.ui_queue.put({"type": "error", "text": f"缺少套件：{exc.name}"})
        except Exception as exc:
            self.ui_queue.put({"type": "error", "text": f"語音辨識失敗：{exc}"})

    def _load_audio_for_timing(self, video_path, sample_rate=16000):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not video_path:
            return None, sample_rate
        cmd = [
            ffmpeg, "-v", "error", "-i", video_path,
            "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            raw = subprocess.check_output(cmd, startupinfo=startupinfo, timeout=120)
        except Exception:
            return None, sample_rate
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return None, sample_rate
        return audio, sample_rate

    def _local_active_edges(self, audio, sample_rate, search_start, search_end):
        if audio is None or sample_rate <= 0 or search_end <= search_start:
            return None
        s0 = int(max(0.0, search_start) * sample_rate)
        s1 = int(max(0.0, search_end) * sample_rate)
        chunk = audio[s0:s1]
        if chunk.size < sample_rate * 0.025:
            return None
        frame_seconds = 0.005
        frame = max(1, int(sample_rate * frame_seconds))
        usable = chunk[: frame * (chunk.size // frame)]
        if usable.size == 0:
            return None
        rms = np.sqrt(np.mean(usable.reshape(-1, frame) ** 2, axis=1))
        if rms.size == 0:
            return None
        floor = float(np.percentile(rms, 25))
        peak = float(np.percentile(rms, 95))
        threshold = max(floor * 2.4, peak * 0.20, 0.005)
        active = np.where(rms >= threshold)[0]
        if active.size == 0:
            return None
        return (
            search_start + active[0] * frame_seconds,
            search_start + (active[-1] + 1) * frame_seconds,
        )

    def _refine_speech_bounds(self, audio, sample_rate, start, end, min_left=0.0, max_right=None, pad=0.025):
        if audio is None or sample_rate <= 0 or end <= start:
            return start, end
        total_duration = audio.size / sample_rate
        max_right = total_duration if max_right is None else min(total_duration, max_right)
        min_left = max(0.0, min_left)

        start_edges = self._local_active_edges(
            audio,
            sample_rate,
            max(min_left, start - 0.18),
            min(max_right, max(start + 0.24, min(end, start + 0.08))),
        )
        end_edges = self._local_active_edges(
            audio,
            sample_rate,
            max(min_left, min(end - 0.24, start + 0.02)),
            min(max_right, end + 0.18),
        )

        refined_start = start_edges[0] if start_edges else start
        refined_end = end_edges[1] if end_edges else end
        refined_start = max(min_left, refined_start - pad)
        refined_end = min(max_right, refined_end + pad)
        if abs(refined_start - start) > 0.28:
            refined_start = start
        if abs(refined_end - end) > 0.28:
            refined_end = end
        if refined_end - refined_start < 0.08:
            return start, end
        return refined_start, refined_end

    def _calibrate_speech_entries(self, entries, audio, sample_rate, min_silence):
        if not entries:
            return []
        entries = sorted(entries, key=lambda item: item["start"])
        calibrated = []
        guard_gap = min(0.08, max(0.02, float(min_silence) * 0.15))
        for idx, item in enumerate(entries):
            prev_end = calibrated[-1]["end"] if calibrated else 0.0
            next_start = entries[idx + 1]["start"] if idx + 1 < len(entries) else None
            min_left = prev_end + guard_gap if calibrated else 0.0
            max_right = next_start - guard_gap if next_start is not None else None
            start, end = self._refine_speech_bounds(
                audio,
                sample_rate,
                item["start"],
                item["end"],
                min_left=min_left,
                max_right=max_right,
            )
            new_item = dict(item)
            new_item["start"] = start
            new_item["end"] = end
            calibrated.append(new_item)
        return calibrated

    def _detect_audio_activity_intervals(self, audio, sample_rate, min_active=0.12, bridge_gap=0.16):
        if audio is None or sample_rate <= 0:
            return []
        frame = max(1, int(sample_rate * 0.01))
        usable = audio[: frame * (audio.size // frame)]
        if usable.size == 0:
            return []
        rms = np.sqrt(np.mean(usable.reshape(-1, frame) ** 2, axis=1))
        return self._activity_intervals_from_levels(rms, 0.01, min_active=min_active, bridge_gap=bridge_gap)

    def _find_uncovered_activity_intervals(self, entries, activity_intervals, min_gap=0.18):
        gaps = []
        if not activity_intervals:
            return gaps
        for start, end in activity_intervals:
            uncovered = [(start, end)]
            for entry in entries:
                next_uncovered = []
                for u_start, u_end in uncovered:
                    if entry["end"] <= u_start or entry["start"] >= u_end:
                        next_uncovered.append((u_start, u_end))
                        continue
                    if entry["start"] > u_start:
                        next_uncovered.append((u_start, min(entry["start"], u_end)))
                    if entry["end"] < u_end:
                        next_uncovered.append((max(entry["end"], u_start), u_end))
                uncovered = next_uncovered
                if not uncovered:
                    break
            gaps.extend((u_start, u_end) for u_start, u_end in uncovered if u_end - u_start >= min_gap)
        return gaps

    def _transcribe_slice(self, model, source_path, start, end):
        if model is None or not source_path or end <= start:
            return []
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        fd, temp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-ss", f"{max(0.0, start):.3f}",
            "-t", f"{max(0.05, end - start):.3f}",
            "-i", source_path,
            "-vn", "-ac", "1", "-ar", "16000", temp_path,
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            if result.returncode != 0 or not os.path.exists(temp_path):
                return []
            segments, _ = model.transcribe(
                temp_path,
                beam_size=5,
                language="zh",
                vad_filter=False,
                word_timestamps=True,
                no_speech_threshold=0.9,
                condition_on_previous_text=False,
            )
            recovered = []
            for segment in segments:
                text = str(segment.text).strip()
                if not text:
                    continue
                words = [word for word in getattr(segment, "words", None) or [] if getattr(word, "word", "").strip()]
                if words:
                    text = "".join(word.word.strip() for word in words).strip() or text
                    seg_start = start + float(words[0].start)
                    seg_end = start + float(words[-1].end)
                else:
                    seg_start = start + float(segment.start)
                    seg_end = start + float(segment.end)
                if text and seg_end - seg_start >= 0.05:
                    recovered.append({"start": seg_start, "end": seg_end, "text": text, "pending": False})
            return recovered
        except Exception:
            return []
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _segments_to_rows(self, segments, total_frames=None, fps=None, min_silence=MIN_SILENCE_SECONDS, audio_path=None, model=None):
        audio, audio_rate = self._load_audio_for_timing(audio_path)
        speech_items = []
        word_gap = max(0.18, min(float(min_silence), 0.75))

        for segment in segments:
            words = [word for word in getattr(segment, "words", None) or [] if getattr(word, "word", "").strip()]
            if words:
                group = []
                for word in words:
                    if group and float(word.start) - float(group[-1].end) >= word_gap:
                        speech_items.append(group)
                        group = []
                    group.append(word)
                if group:
                    speech_items.append(group)
            else:
                text = segment.text.strip()
                if text:
                    speech_items.append(segment)

        entries = []
        for item in speech_items:
            if isinstance(item, list):
                text = "".join(word.word.strip() for word in item).strip()
                start = float(item[0].start)
                end = float(item[-1].end)
            else:
                text = item.text.strip()
                start = float(item.start)
                end = float(item.end)
            if not text or end <= start:
                continue
            entries.append({"start": start, "end": end, "text": text, "pending": False})

        entries = self._calibrate_speech_entries(entries, audio, audio_rate, min_silence)

        activity_intervals = self._detect_audio_activity_intervals(
            audio,
            audio_rate,
            min_active=0.10,
            bridge_gap=max(0.08, min(float(min_silence) * 0.45, 0.22)),
        )
        gaps = self._find_uncovered_activity_intervals(
            entries,
            activity_intervals,
            min_gap=max(0.18, min(float(min_silence), 0.5)),
        )
        recovered_count = 0
        for start, end in gaps:
            recovered = self._transcribe_slice(model, audio_path, start, end)
            if recovered:
                entries.extend(recovered)
                recovered_count += len(recovered)
        if recovered_count:
            self.ui_queue.put({"type": "error_log", "text": f"已針對漏辨聲音區段補辨識 {recovered_count} 句。"})

        entries = self._calibrate_speech_entries(entries, audio, audio_rate, min_silence)
        entries.sort(key=lambda item: item["start"])
        cleaned = []
        for item in entries:
            if cleaned and item["start"] < cleaned[-1]["end"]:
                boundary = (cleaned[-1]["end"] + item["start"]) / 2
                cleaned[-1]["end"] = max(cleaned[-1]["start"] + 0.05, boundary)
                item["start"] = max(cleaned[-1]["end"], item["start"])
            if item["end"] - item["start"] >= 0.05:
                cleaned.append(item)

        rows = []
        last_end = 0.0
        for index, item in enumerate(cleaned, start=1):
            if item["start"] - last_end >= min_silence:
                rows.append({
                    "時間點": format_time_range(last_end, item["start"]),
                    "說話者": SILENCE_SPEAKER,
                    "對話內容": SILENCE_TEXT,
                })
            rows.append({
                "時間點": format_time_range(item["start"], item["end"]),
                "說話者": self.renderer.yolo_id_to_speaker.get(1, "人物 1"),
                "對話內容": item["text"],
            })
            last_end = max(last_end, float(item["end"]))
            if index % 3 == 0:
                self.ui_queue.put({"type": "progress", "value": min(len(rows) / 80, 0.95)})
        video_end = None
        if total_frames and fps:
            video_end = total_frames / max(fps, 1)
        if video_end and video_end - last_end >= min_silence:
            rows.append({
                "時間點": format_time_range(last_end, video_end),
                "說話者": SILENCE_SPEAKER,
                "對話內容": SILENCE_TEXT,
            })
        return rows

    def on_speech_done(self, rows, out_csv):
        self.btn_speech.configure(state="normal", text="3  重新辨識聲音")
        self.btn_data.configure(state="normal")
        self.whisper_menu.configure(state="normal")
        self.btn_scan.configure(state="normal" if self.people_count_confirmed else "disabled")
        self.progress_bar.set(1)
        silence_count = sum(1 for row in rows if row.get("說話者") == SILENCE_SPEAKER)
        df = pd.DataFrame(rows)
        self.renderer.data_processor.set_dataframe(df, os.path.basename(out_csv))
        self.selected_dialogue_row = 0 if len(df) else None
        self.refresh_script_panel()
        self.log(f"語音辨識完成，已產生腳本：{os.path.basename(out_csv)}，無講話 {silence_count} 段")

    def on_worker_error(self, text):
        self.btn_speech.configure(state="normal", text="3  辨識聲音產生腳本")
        self.btn_data.configure(state="normal")
        self.whisper_menu.configure(state="normal")
        self.btn_scan.configure(state="normal" if self.renderer.data_processor.has_data() else "disabled", text="4  掃描人物並對應")
        self.btn_export.configure(state="normal" if self.renderer.tracking_data else "disabled", text="5  匯出影片")
        self.log(text)
        messagebox.showerror(APP_TITLE, text)

    def start_preview_scan(self):
        self.stop_preview_playback()
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        if not self.people_count_confirmed:
            messagebox.showinfo(APP_TITLE, "請先框選人物並確認框選。")
            return
        if not self.renderer.data_processor.has_data():
            messagebox.showinfo(APP_TITLE, "請先辨識聲音產生腳本，或載入既有腳本。")
            return
        self.renderer.expected_people_count = len(self.renderer.person_rois)
        self.btn_scan.configure(state="disabled", text="掃描中...")
        self.btn_export.configure(state="disabled")
        self.slider_timeline.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始掃描人物。第一次執行會載入 YOLO 模型，請稍等。")
        threading.Thread(target=self.renderer.scan_video, daemon=True).start()

    def on_scan_finished(self):
        self.btn_scan.configure(state="normal", text="4  重新掃描並對應")
        if self.renderer.tracking_data:
            self.slider_timeline.configure(state="normal", from_=1, to=max(1, self.renderer.total_frames))
            self.slider_timeline.set(1)
            self.btn_export.configure(state="normal")
            first_frame = next((idx for idx, boxes in self.renderer.tracking_data.items() if boxes), 1)
            self.slider_timeline.set(first_frame)
            self.on_timeline_scrub(first_frame)
            ids = sorted({box["id"] for boxes in self.renderer.tracking_data.values() for box in boxes})
            self.log(f"掃描完成，找到 ID：{', '.join(map(str, ids)) if ids else '無'}")
            if ids:
                self.open_speaker_mapper(ids)
        else:
            self.log("掃描完成，但沒有找到人物。")

    def start_export(self):
        self.stop_preview_playback()
        if not self.renderer.tracking_data:
            messagebox.showinfo(APP_TITLE, "請先掃描人物。")
            return
        self._sync_selected_person_fields()
        self.stop_audio_preview()
        self.btn_export.configure(state="disabled", text="匯出中...")
        self.btn_scan.configure(state="disabled")
        self.slider_timeline.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始匯出影片。")
        threading.Thread(target=self.renderer.export_video, daemon=True).start()

    def on_export_finished(self, out_path):
        self.btn_export.configure(state="normal", text="5  匯出影片")
        self.btn_scan.configure(state="normal", text="4  重新掃描並對應")
        self.slider_timeline.configure(state="normal")
        self.progress_bar.set(1)
        if out_path:
            self.log(f"匯出完成：{out_path}")
        else:
            self.log("匯出未完成。")

    def open_speaker_mapper(self, ids):
        win = ctk.CTkToplevel(self)
        win.title("命名人物")
        win.geometry("520x420")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="先替每個人物框命名。腳本選單之後會出現這些名字。", font=("Microsoft JhengHei UI", 16, "bold")).pack(pady=(16, 8))
        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(expand=True, fill="both", padx=14, pady=8)
        rows = []
        suggestions = self.renderer.data_processor.get_unique_speakers()
        for tid in ids:
            row = ctk.CTkFrame(scroll)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"人物 {tid}", width=70, font=("Arial", 13, "bold")).pack(side="left", padx=8, pady=8)
            value = self.renderer.yolo_id_to_speaker.get(tid, f"人物 {tid}")
            entry = ctk.CTkEntry(row, width=160)
            entry.insert(0, value)
            entry.pack(side="left", padx=6)
            if suggestions:
                menu_var = ctk.StringVar(value=value if value else suggestions[0])
                menu = ctk.CTkOptionMenu(row, values=suggestions, variable=menu_var, command=lambda val, ent=entry: self._set_entry(ent, val))
                menu.pack(side="left", padx=6)
            rows.append((tid, entry))

        def save():
            self.push_undo_state("修改人物名稱")
            for tid, entry in rows:
                speaker = entry.get().strip()
                if speaker:
                    self.renderer.yolo_id_to_speaker[tid] = speaker
            self.renderer.bubble_cache.clear()
            self.log("已更新人物名稱。腳本選單會使用這些名字。")
            self.on_timeline_scrub(self.slider_timeline.get())
            self.refresh_script_panel()
            win.destroy()

        ctk.CTkButton(win, text="套用", command=save, height=36).pack(pady=(6, 16))

    def _set_entry(self, entry, value):
        entry.delete(0, "end")
        entry.insert(0, value)

    def set_preview_image(self, pil_img, reset_view=False):
        old_size = self.preview_pil_orig.size if self.preview_pil_orig is not None else None
        self.preview_pil_orig = pil_img
        if reset_view or old_size != self.preview_pil_orig.size:
            self.preview_zoom = 1.0
            self.canvas_offset = [0, 0]
        if self.renderer.video_width and self.preview_pil_orig:
            self.preview_scale_x = self.preview_pil_orig.size[0] / self.renderer.video_width
            self.preview_scale_y = self.preview_pil_orig.size[1] / self.renderer.video_height
        self._refresh_canvas()

    def _refresh_canvas(self):
        if self.preview_pil_orig is None:
            return
        ow, oh = self.preview_pil_orig.size
        nw = max(1, int(ow * self.preview_zoom))
        nh = max(1, int(oh * self.preview_zoom))
        scaled = self.preview_pil_orig.resize((nw, nh), Image.Resampling.LANCZOS)
        self._canvas_tk_img = ImageTk.PhotoImage(scaled)
        cw = self.preview_canvas.winfo_width() or 600
        ch = self.preview_canvas.winfo_height() or 400
        cx = cw // 2 + self.canvas_offset[0]
        cy = ch // 2 + self.canvas_offset[1]
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(cx, cy, anchor="center", image=self._canvas_tk_img)
        self._draw_person_rois_on_canvas()
        self.preview_canvas.create_text(cw - 8, ch - 8, anchor="se", text=f"{int(self.preview_zoom * 100)}%", fill="#AAB0C0", font=("Consolas", 11))

    def _draw_person_rois_on_canvas(self):
        for idx, roi in enumerate(self.renderer.person_rois, start=1):
            x1, y1 = self._video_to_canvas(roi[0], roi[1])
            x2, y2 = self._video_to_canvas(roi[2], roi[3])
            self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline="#43E2A8", width=3)
            self.preview_canvas.create_text(
                x1 + 8, y1 + 8,
                anchor="nw",
                text=f"人物 {idx}",
                fill="#43E2A8",
                font=("Microsoft JhengHei UI", 12, "bold"),
            )

    def _video_to_canvas(self, x, y):
        cw = self.preview_canvas.winfo_width() or 600
        ch = self.preview_canvas.winfo_height() or 400
        center_x = cw // 2 + self.canvas_offset[0]
        center_y = ch // 2 + self.canvas_offset[1]
        ow, oh = self.preview_pil_orig.size if self.preview_pil_orig else (600, 400)
        img_x = x * self.preview_scale_x
        img_y = y * self.preview_scale_y
        return (
            center_x + (img_x - ow / 2) * self.preview_zoom,
            center_y + (img_y - oh / 2) * self.preview_zoom,
        )

    def _canvas_to_video(self, x, y):
        if not self.preview_pil_orig:
            return 0, 0
        cw = self.preview_canvas.winfo_width() or 600
        ch = self.preview_canvas.winfo_height() or 400
        center_x = cw // 2 + self.canvas_offset[0]
        center_y = ch // 2 + self.canvas_offset[1]
        ow, oh = self.preview_pil_orig.size
        img_x = (x - center_x) / self.preview_zoom + ow / 2
        img_y = (y - center_y) / self.preview_zoom + oh / 2
        return img_x / max(self.preview_scale_x, 1e-6), img_y / max(self.preview_scale_y, 1e-6)

    def _on_canvas_scroll(self, event):
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.preview_zoom = max(0.15, min(8.0, self.preview_zoom * factor))
        self._refresh_canvas()

    def _on_canvas_motion(self, event):
        if self._canvas_mode == "person_roi":
            self.preview_canvas.configure(cursor="crosshair")
            return
        if self._canvas_mode == "bubble":
            self.preview_canvas.configure(cursor="fleur")
            return
        if self._hit_bubble(event.x, event.y) is not None:
            self.preview_canvas.configure(cursor="hand2")
        elif self._hit_box(event.x, event.y) is not None:
            self.preview_canvas.configure(cursor="hand2")
        else:
            self.preview_canvas.configure(cursor="crosshair")

    def _on_canvas_drag_start(self, event):
        self.preview_canvas.focus_set()
        self._drag_start = (event.x, event.y)
        self._drag_offset_start = list(self.canvas_offset)
        self._drag_moved = False
        if self._canvas_mode == "person_roi":
            self._roi_start = (event.x, event.y)
            if self._roi_rect_id:
                self.preview_canvas.delete(self._roi_rect_id)
                self._roi_rect_id = None
        elif self._canvas_mode == "bubble":
            self._bubble_drag_tid = self._nearest_box_id(event.x, event.y)
            if self._bubble_drag_tid is not None:
                self.push_undo_state("移動字幕泡泡")
                self._bubble_drag_start_canvas = (event.x, event.y)
                self._bubble_drag_start_offset = self.renderer.bubble_offsets.get(self._bubble_drag_tid, (0, 0))
        else:
            bubble_tid = self._hit_bubble(event.x, event.y)
            if bubble_tid is not None:
                self._canvas_mode = "bubble"
                self.push_undo_state("移動字幕泡泡")
                self._bubble_drag_tid = bubble_tid
                self._bubble_drag_start_canvas = (event.x, event.y)
                self._bubble_drag_start_offset = self.renderer.bubble_offsets.get(bubble_tid, (0, 0))
                self.select_person(bubble_tid)
                self.preview_canvas.configure(cursor="fleur")

    def _on_canvas_drag(self, event):
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._drag_moved = self._drag_moved or abs(dx) > 3 or abs(dy) > 3
        if self._canvas_mode == "person_roi":
            if self._roi_rect_id:
                self.preview_canvas.delete(self._roi_rect_id)
            sx, sy = self._roi_start
            self._roi_rect_id = self.preview_canvas.create_rectangle(sx, sy, event.x, event.y, outline="#43E2A8", width=2, dash=(6, 3))
        elif self._canvas_mode == "bubble" and self._bubble_drag_tid is not None:
            ox, oy = self._bubble_drag_start_offset
            vx = int((event.x - self._bubble_drag_start_canvas[0]) / max(self.preview_scale_x * self.preview_zoom, 1e-6))
            vy = int((event.y - self._bubble_drag_start_canvas[1]) / max(self.preview_scale_y * self.preview_zoom, 1e-6))
            self.renderer.bubble_offsets[self._bubble_drag_tid] = (ox + vx, oy + vy)
            self.renderer.bubble_cache.clear()
            if hasattr(self, "_drag_preview_after_id"):
                self.after_cancel(self._drag_preview_after_id)
            self._drag_preview_after_id = self.after(30, lambda: self.on_timeline_scrub(self.slider_timeline.get()))
        else:
            self.canvas_offset[0] = self._drag_offset_start[0] + dx
            self.canvas_offset[1] = self._drag_offset_start[1] + dy
            self._refresh_canvas()

    def _on_canvas_release(self, event):
        if self._canvas_mode == "person_roi":
            if self._drag_moved:
                vx1, vy1 = self._canvas_to_video(*self._roi_start)
                vx2, vy2 = self._canvas_to_video(event.x, event.y)
                x1, x2 = sorted((int(vx1), int(vx2)))
                y1, y2 = sorted((int(vy1), int(vy2)))
                if abs(x2 - x1) >= 20 and abs(y2 - y1) >= 20:
                    self.renderer.person_rois.append((max(0, x1), max(0, y1), max(0, x2), max(0, y2)))
                    self.mark_people_count_unconfirmed()
                    self.btn_clear_people.configure(state="normal")
                    self.log(f"已加入人物框 {len(self.renderer.person_rois)}。框完請按確認框選。")
            self._canvas_mode = "pan"
            self.btn_draw_people.configure(text="2  框選要追蹤的人", fg_color=None)
            self._refresh_canvas()
        elif self._canvas_mode == "bubble":
            self._bubble_drag_tid = None
            self._canvas_mode = "pan"
            self.preview_canvas.configure(cursor="hand2" if self._hit_bubble(event.x, event.y) is not None else "crosshair")
        elif not self._drag_moved:
            self.on_preview_click(event)

    def _on_canvas_right_click(self, event):
        self.preview_canvas.focus_set()
        tid = self._hit_bubble(event.x, event.y)
        if tid is None:
            tid = self._hit_box(event.x, event.y)
        if tid is None:
            return
        self.assign_current_dialogue_to_person(tid)

    def assign_current_dialogue_to_person(self, tid):
        if not self.renderer.data_processor.has_data():
            return
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            frame_idx = 1
        row_idx = self.selected_dialogue_row
        if row_idx is None:
            row_idx, _ = self.renderer.data_processor.find_dialogue_at_time(frame_idx, self.renderer.fps)
        if row_idx is None:
            self.log("目前時間點沒有可改說話者的對話。")
            return
        speaker = self.renderer.yolo_id_to_speaker.get(int(tid), f"人物 {int(tid)}")
        self.push_undo_state("畫布指定說話者")
        if self.renderer.data_processor.update_dialogue_speaker(row_idx, speaker):
            self.selected_dialogue_row = row_idx
            self.renderer.bubble_cache.clear()
            self._loading_person_fields = True
            self.entry_id.delete(0, "end")
            self.entry_id.insert(0, str(int(tid)))
            self.entry_speaker.delete(0, "end")
            self.entry_speaker.insert(0, speaker)
            _, text = self.renderer.data_processor.get_dialogue_row_values(row_idx)
            self.entry_text.delete(0, "end")
            self.entry_text.insert(0, text)
            self._loading_person_fields = False
            self.log(f"已把目前這句改成 {speaker}。")
            self.refresh_current_preview()

    def _nearest_box_id(self, x, y):
        if not self.preview_boxes:
            return None
        vx, vy = self._canvas_to_video(x, y)
        best_id = None
        best_dist = 1e9
        for box in self.preview_boxes:
            x1, y1, x2, y2 = box["bbox"]
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            dist = abs(vx - cx) + abs(vy - cy)
            if dist < best_dist:
                best_dist = dist
                best_id = box["id"]
        return best_id

    def _hit_bubble(self, x, y):
        vx, vy = self._canvas_to_video(x, y)
        for tid, rect in self.renderer.bubble_rects.items():
            x1, y1, x2, y2 = rect
            pad = 8
            if x1 - pad <= vx <= x2 + pad and y1 - pad <= vy <= y2 + pad:
                return tid
        return None

    def _hit_box(self, x, y):
        vx, vy = self._canvas_to_video(x, y)
        for box in self.preview_boxes:
            x1, y1, x2, y2 = box["bbox"]
            if x1 <= vx <= x2 and y1 <= vy <= y2:
                return box["id"]
        for idx, roi in enumerate(self.renderer.person_rois, start=1):
            x1, y1, x2, y2 = roi
            if x1 <= vx <= x2 and y1 <= vy <= y2:
                return idx
        return None

    def on_preview_click(self, event):
        self.preview_canvas.focus_set()
        tid = self._hit_bubble(event.x, event.y)
        if tid is None:
            tid = self._hit_box(event.x, event.y)
        if tid is not None:
            self.select_person(tid)

    def select_person(self, tid, allow_time_fallback=True):
        tid = int(tid)
        self._loading_person_fields = True
        self.entry_id.delete(0, "end")
        self.entry_id.insert(0, str(tid))
        speaker = self.renderer.yolo_id_to_speaker.get(tid, "")
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, speaker)
        self.selected_dialogue_row = None
        text = ""
        if self.slider_timeline.cget("state") == "normal":
            try:
                frame_idx = int(float(self.slider_timeline.get()))
                row_idx, text = self.renderer.data_processor.find_dialogue_row(
                    frame_idx,
                    self.renderer.fps,
                    tid,
                    speaker,
                )
                if row_idx is None and allow_time_fallback:
                    row_idx, text = self.renderer.data_processor.find_dialogue_at_time(
                        frame_idx,
                        self.renderer.fps,
                    )
                self.selected_dialogue_row = row_idx
            except Exception:
                text = ""
        self.entry_text.delete(0, "end")
        self.entry_text.insert(0, text)
        self._loading_person_fields = False
        if self.selected_dialogue_row is None:
            self.log(f"已選取 ID {tid}，目前時間點沒有對應腳本列。")
        else:
            self.log(f"已選取 ID {tid}，正在編輯目前這一句。")

    def refresh_current_preview(self):
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            return
        self.update_timecode_and_waveform(frame_idx)
        self._render_scrub(frame_idx)

    def sync_fields_for_frame(self, frame_idx, strict_current_id=False):
        if self._loading_person_fields:
            return
        previous_row = self.selected_dialogue_row
        try:
            current_tid = int(self.entry_id.get())
        except ValueError:
            current_tid = 1
        speaker = self.renderer.yolo_id_to_speaker.get(current_tid, "")
        row_idx, text = self.renderer.data_processor.find_dialogue_row(
            frame_idx,
            self.renderer.fps,
            current_tid,
            speaker,
        )
        if row_idx is None and not strict_current_id:
            row_idx, text = self.renderer.data_processor.find_dialogue_at_time(
                frame_idx,
                self.renderer.fps,
            )
        self.selected_dialogue_row = row_idx
        if row_idx is None:
            if strict_current_id:
                self._loading_person_fields = True
                self.entry_text.delete(0, "end")
                self._loading_person_fields = False
            return

        row_speaker, row_text = self.renderer.data_processor.get_dialogue_row_values(row_idx)
        if strict_current_id:
            matched_tid = current_tid
        else:
            matched_tid = next(
                (tid for tid, name in self.renderer.yolo_id_to_speaker.items() if name == row_speaker),
                current_tid,
            )
        self._loading_person_fields = True
        self.entry_id.delete(0, "end")
        self.entry_id.insert(0, str(matched_tid))
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, row_speaker or speaker)
        self.entry_text.delete(0, "end")
        self.entry_text.insert(0, row_text or text)
        self._loading_person_fields = False
        if previous_row != self.selected_dialogue_row:
            self.update_script_selection_styles()

    def on_timeline_scrub(self, value):
        frame_idx = max(1, int(float(value)))
        if self.preview_playing:
            self.stop_preview_playback()
        self.update_timecode_and_waveform(frame_idx)
        self.sync_fields_for_frame(frame_idx)
        if hasattr(self, "_scrub_after_id"):
            self.after_cancel(self._scrub_after_id)
        self._scrub_after_id = self.after(80, lambda: self._render_scrub(frame_idx))

    def update_timecode_and_waveform(self, frame_idx):
        if self.renderer.fps:
            seconds = int(frame_to_seconds(frame_idx, self.renderer.fps))
            mm, ss = divmod(seconds, 60)
            hh, mm = divmod(mm, 60)
            self.lbl_timecode.configure(text=f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}")
        self.draw_waveform(frame_idx)

    def _render_scrub(self, frame_idx):
        self._preview_render_pending = True
        self._preview_request_id += 1
        request_id = self._preview_request_id

        def worker():
            img = self.renderer.get_preview_frame(frame_idx)
            if img is None:
                self.ui_queue.put({"type": "preview_done", "request_id": request_id})
                return
            self.ui_queue.put({
                "type": "preview",
                "request_id": request_id,
                "img": img,
                "boxes": self.renderer.tracking_data.get(frame_idx, []),
            })

        threading.Thread(target=worker, daemon=True).start()

    def play_audio_preview(self, frame_idx, duration=0.35, force=False):
        if not self.renderer.video_path or not self.renderer.fps:
            return
        ffplay = shutil.which("ffplay")
        if not ffplay:
            return
        seconds = frame_to_seconds(frame_idx, self.renderer.fps)
        if not force and abs(seconds - self._last_audio_preview_at) < 0.12:
            return
        self._last_audio_preview_at = seconds
        self.stop_audio_preview()
        cmd = [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            "-ss", f"{seconds:.2f}",
            "-t", f"{duration:.2f}",
            self._audio_preview_source(),
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            self._ffplay_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
            )
        except Exception:
            self._ffplay_process = None

    def _audio_preview_source(self):
        if self._waveform_audio_path and os.path.exists(self._waveform_audio_path):
            return self._waveform_audio_path
        return get_safe_path(self.renderer.video_path)

    def _clear_waveform_audio_cache(self):
        old_path = getattr(self, "_waveform_audio_path", None)
        self._waveform_audio_path = None
        if old_path:
            try:
                if os.path.exists(old_path):
                    os.remove(old_path)
            except OSError:
                pass

    def stop_audio_preview(self):
        proc = self._ffplay_process
        self._ffplay_process = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def on_close(self):
        self.stop_preview_playback()
        self.stop_audio_preview()
        self._clear_waveform_audio_cache()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
