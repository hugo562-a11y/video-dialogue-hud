"""VideoRenderer — 負責 YOLO 追蹤、字幕氣泡渲染與影片匯出。"""
from __future__ import annotations

import os
import random
import shutil
import string
import subprocess
import tempfile

import threading

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core.constants import (
    MODEL_PATH, FONT_NAME, MAX_PREVIEW_SIZE, ROOT_DIR,
    get_safe_path,
)
from core.data_processor import DataProcessor
from core.utils import (
    normalize_time_ranges,
    frame_to_seconds,
    available_output_path,
)

BUBBLE_STYLE_OPTIONS = ["classic", "oval", "capsule", "tech", "sharp"]
BUBBLE_POSITION_OPTIONS = ["auto", "top", "bottom", "left", "right"]
BUBBLE_COLOR_OPTIONS = {
    "藍": ((31, 127, 181, 235), (255, 255, 255, 255)),
    "紅": ((205, 73, 73, 235), (255, 255, 255, 255)),
    "綠": ((49, 163, 98, 235), (255, 255, 255, 255)),
    "黃": ((230, 177, 54, 240), (20, 20, 20, 255)),
    "紫": ((118, 91, 171, 235), (255, 255, 255, 255)),
    "青": ((37, 161, 154, 235), (255, 255, 255, 255)),
}
_BUBBLE_COLOR_NAMES = list(BUBBLE_COLOR_OPTIONS.keys())
_BUBBLE_POSITION_DEFAULTS = ["top", "bottom", "right", "left"]


class VideoRenderer:
    def __init__(self, ui_callback=None):
        self.ui_callback = ui_callback
        self.yolo_model = None
        self.video_path: str | None = None
        self.source_video_path: str | None = None
        self.data_processor = DataProcessor()

        self.settings: dict = {"bubble_pos": "auto"}
        self.style: dict = {"font_size": 72, "font_color": (255, 255, 255, 255)}
        self.person_styles: dict = {}

        self.is_processing = False
        self.tracking_data: dict = {}
        self.yolo_id_to_speaker: dict = {}
        self.last_positions: dict = {}
        self.bubble_offsets: dict = {}
        self.bubble_rects: dict = {}
        self.bubble_cache: dict = {}
        self.person_rois: list = []
        self.expected_people_count = 2
        self.cut_ranges: list = []

        self.total_frames = 0
        self.fps: float = 30
        self.video_width = 0
        self.video_height = 0
        self._preview_cap = None
        self._preview_cap_path: str | None = None
        self._preview_lock = threading.Lock()
        self.font_path = self._font_path()

    # ------------------------------------------------------------------ 初始化
    def _font_path(self) -> str:
        local = os.path.join(ROOT_DIR, FONT_NAME)
        if os.path.exists(local):
            return local
        return "msjh.ttc"

    def ensure_model(self):
        if self.yolo_model is None:
            from ultralytics import YOLO
            model_path = os.path.join(ROOT_DIR, MODEL_PATH)
            self.yolo_model = YOLO(model_path if os.path.exists(model_path) else MODEL_PATH)

    def set_video_resolution(self, width: int, height: int) -> int:
        self.video_width = width
        self.video_height = height
        auto_size = max(24, min(160, int(height / 15)))
        self.style["font_size"] = auto_size
        self.bubble_cache.clear()
        return auto_size

    # ------------------------------------------------------------------ 字型
    def _load_font(self, size: int):
        for candidate in (self.font_path, "msjh.ttc", "arial.ttf"):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _wrap_text(self, text: str, limit: int = 14) -> str:
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

    # ------------------------------------------------------------------ 氣泡
    def default_bubble_color_name(self, track_id: int) -> str:
        return _BUBBLE_COLOR_NAMES[int(track_id) % len(_BUBBLE_COLOR_NAMES)]

    def bubble_color_rgb(self, track_id: int) -> tuple[int, int, int]:
        color_name = self.get_person_bubble_style(track_id)["color"]
        rgba, _ = BUBBLE_COLOR_OPTIONS[color_name]
        return int(rgba[0]), int(rgba[1]), int(rgba[2])

    def bubble_color_hex(self, track_id: int) -> str:
        red, green, blue = self.bubble_color_rgb(track_id)
        return f"#{red:02X}{green:02X}{blue:02X}"

    def bubble_text_hex(self, track_id: int) -> str:
        red, green, blue = self.bubble_color_rgb(track_id)
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return "#111827" if luminance >= 150 else "#FFFFFF"

    def default_bubble_position(self, track_id: int) -> str:
        return _BUBBLE_POSITION_DEFAULTS[(max(1, int(track_id or 1)) - 1) % len(_BUBBLE_POSITION_DEFAULTS)]

    def get_person_bubble_style(self, track_id: int) -> dict:
        track_id = int(track_id or 0)
        existing = self.person_styles.get(track_id, {})
        style_name = existing.get("style") or "classic"
        color_name = existing.get("color") or self.default_bubble_color_name(track_id)
        position = existing.get("position") or self.default_bubble_position(track_id)
        if style_name not in BUBBLE_STYLE_OPTIONS:
            style_name = "classic"
        if color_name not in BUBBLE_COLOR_OPTIONS:
            color_name = self.default_bubble_color_name(track_id)
        if position not in BUBBLE_POSITION_OPTIONS:
            position = self.default_bubble_position(track_id)
        return {"style": style_name, "color": color_name, "position": position}

    def set_person_bubble_style(
        self,
        track_id: int,
        style_name: str | None = None,
        color_name: str | None = None,
        position: str | None = None,
    ):
        track_id = int(track_id or 0)
        current = self.get_person_bubble_style(track_id)
        if style_name in BUBBLE_STYLE_OPTIONS:
            current["style"] = style_name
        if color_name in BUBBLE_COLOR_OPTIONS:
            current["color"] = color_name
        if position in BUBBLE_POSITION_OPTIONS:
            current["position"] = position
        self.person_styles[track_id] = current
        self.bubble_cache.clear()

    def get_speech_bubble_img(self, text: str, pos: str = "top", track_id: int = 0):
        person_style = self.get_person_bubble_style(track_id)
        style = person_style["style"]
        color_name = person_style["color"]
        cache_key = (text, pos, track_id, style, color_name, self.style["font_size"], self.style["font_color"])
        if cache_key in self.bubble_cache:
            return self.bubble_cache[cache_key]

        scale = 3
        font_size = int(self.style["font_size"]) * scale
        font = self._load_font(font_size)
        wrapped = self._wrap_text(text)

        bg_col, default_text_col = BUBBLE_COLOR_OPTIONS[color_name]
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

    def draw_speech_bubble(self, frame, text: str, target_id: int, all_boxes: list, draw_connector: bool = False):
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
            "top":    (center_x - bw // 2, int(y1) - bh - 8),
            "bottom": (center_x - bw // 2, int(y2) + 8),
            "left":   (int(x1) - bw - 8,   int(y1)),
            "right":  (int(x2) + 8,          int(y1)),
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

        pos_setting = self.get_person_bubble_style(target_id).get("position", "auto")
        if pos_setting in positions:
            chosen = pos_setting
        else:
            preferred = self.default_bubble_position(target_id)
            order = [self.last_positions.get(target_id, preferred), preferred, "top", "bottom", "right", "left"]
            chosen = next((p for p in order if p in positions and not blocked(*positions[p])), "top")
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
        if draw_connector:
            self._draw_bubble_connector(frame, target, chosen, (px, py, px + bw, py + bh))
        overlay = bubble[0:y_end - py, 0:x_end - px]
        alpha = overlay[:, :, 3] / 255.0
        for channel in range(3):
            frame[py:y_end, px:x_end, channel] = (
                alpha * overlay[:, :, channel] + (1.0 - alpha) * frame[py:y_end, px:x_end, channel]
            ).astype(np.uint8)

    def _draw_bubble_connector(self, frame, target: dict, position: str, rect: tuple[int, int, int, int]):
        fh, fw = frame.shape[:2]
        bx1, by1, bx2, by2 = rect
        x1, y1, x2, y2 = target["bbox"]
        mouth_x = int((x1 + x2) / 2)
        mouth_y = int(y1 + max(1, y2 - y1) * 0.68)
        mouth_x = max(0, min(fw - 1, mouth_x))
        mouth_y = max(0, min(fh - 1, mouth_y))

        bubble_anchor = self._connector_bubble_anchor(position, rect)
        target_anchor = self._connector_target_anchor(position, (x1, y1, x2, y2), mouth_x, mouth_y)
        ax = max(0, min(fw - 1, int(bubble_anchor[0])))
        ay = max(0, min(fh - 1, int(bubble_anchor[1])))
        tx = max(0, min(fw - 1, int(target_anchor[0])))
        ty = max(0, min(fh - 1, int(target_anchor[1])))

        mid_x = (ax + tx) / 2
        mid_y = (ay + ty) / 2
        if position in {"top", "bottom"}:
            bend = -abs(ty - ay) * 0.16 if position == "bottom" else abs(ty - ay) * 0.16
            control = (mid_x, mid_y + bend)
        else:
            bend = -abs(tx - ax) * 0.16 if position == "right" else abs(tx - ax) * 0.16
            control = (mid_x + bend, mid_y)
        curve = self._quadratic_curve((ax, ay), control, (tx, ty))

        overlay = frame.copy()
        cv2.polylines(overlay, [curve], False, (20, 24, 32), 3, cv2.LINE_AA)
        cv2.polylines(overlay, [curve], False, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(overlay, (tx, ty), 2, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.58, frame, 0.42, 0, frame)

    def _connector_bubble_anchor(self, position: str, rect: tuple[int, int, int, int]) -> tuple[float, float]:
        bx1, by1, bx2, by2 = rect
        if position == "bottom":
            return (bx1 + bx2) / 2, by1
        if position == "left":
            return bx2, (by1 + by2) / 2
        if position == "right":
            return bx1, (by1 + by2) / 2
        return (bx1 + bx2) / 2, by2

    def _connector_target_anchor(
        self,
        position: str,
        bbox: tuple[float, float, float, float],
        mouth_x: int,
        mouth_y: int,
    ) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        if position == "bottom":
            return mouth_x, y2
        if position == "top":
            return mouth_x, y1 + (y2 - y1) * 0.70
        if position == "left":
            return x1, mouth_y
        if position == "right":
            return x2, mouth_y
        return mouth_x, mouth_y

    def _quadratic_curve(self, start, control, end, steps: int = 24):
        points = []
        for index in range(steps + 1):
            t = index / steps
            inv = 1.0 - t
            x = inv * inv * start[0] + 2 * inv * t * control[0] + t * t * end[0]
            y = inv * inv * start[1] + 2 * inv * t * control[1] + t * t * end[1]
            points.append((int(round(x)), int(round(y))))
        return np.array(points, dtype=np.int32)

    # ------------------------------------------------------------------ 掃描
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
        last_person_boxes: dict = {}
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
                    self.ui_callback("progress", min(frame_count / max(limit, 1), 1.0))
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

    def _scan_person_rois(self, frame, last_person_boxes: dict) -> list:
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

    def _best_person_box(self, crop, offset_x: int, offset_y: int):
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

    def _head_box_from_full_body(self, box) -> tuple:
        x1, y1, x2, y2 = box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        head_h = min(int(width * 1.05), int(height * 0.42), height)
        return (int(x1), int(y1), int(x2), int(y1 + head_h))

    def _smooth_box(self, old_box, new_box, alpha: float = 0.35) -> tuple:
        return tuple(int((1 - alpha) * old + alpha * new) for old, new in zip(old_box, new_box))

    def _clamp_roi(self, roi, width: int, height: int) -> tuple:
        x1, y1, x2, y2 = roi
        x1, x2 = sorted((int(x1), int(x2)))
        y1, y2 = sorted((int(y1), int(y2)))
        return (
            max(0, min(width, x1)), max(0, min(height, y1)),
            max(0, min(width, x2)), max(0, min(height, y2)),
        )

    # ------------------------------------------------------------------ 說話者映射
    def _assign_default_speakers(self, max_people: int):
        speakers = self.data_processor.get_unique_speakers()
        self.yolo_id_to_speaker = {
            idx + 1: self.yolo_id_to_speaker.get(
                idx + 1,
                speakers[idx] if idx < len(speakers) else f"人物 {idx + 1}",
            )
            for idx in range(max_people)
        }

    def _auto_assign_speaker(self, track_id: int):
        if track_id in self.yolo_id_to_speaker:
            return
        speakers = self.data_processor.get_unique_speakers()
        if len(self.yolo_id_to_speaker) < len(speakers):
            self.yolo_id_to_speaker[track_id] = speakers[len(self.yolo_id_to_speaker)]

    def consolidate_tracking_ids(self, max_people: int):
        max_people = max(1, int(max_people or 1))
        stats: dict = {}
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
            centers.append({"id": tid, "count": count, "x": item["sum_x"] / count, "y": item["sum_y"] / count})

        seeds = sorted(centers, key=lambda c: c["count"], reverse=True)[:max_people]
        seeds = sorted(seeds, key=lambda c: c["x"])
        id_map = {}
        for center in centers:
            best_index = min(
                range(len(seeds)),
                key=lambda i: abs(center["x"] - seeds[i]["x"]) + 0.35 * abs(center["y"] - seeds[i]["y"]),
            )
            id_map[center["id"]] = best_index + 1

        for frame_idx, boxes in list(self.tracking_data.items()):
            merged: dict = {}
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
            idx + 1: self.yolo_id_to_speaker.get(
                idx + 1,
                speakers[idx] if idx < len(speakers) else f"人物 {idx + 1}",
            )
            for idx in range(max_people)
        }
        self.last_positions.clear()
        self.bubble_offsets.clear()
        self.bubble_cache.clear()

    # ------------------------------------------------------------------ 預覽幀
    def _text_for_track(self, frame_idx: int, track_id: int) -> str:
        speaker = self.yolo_id_to_speaker.get(track_id, "")
        if not self.data_processor.has_data():
            return speaker  # 無腳本時顯示人物名稱，讓使用者確認追蹤結果
        return self.data_processor.get_dialogue(frame_idx, self.fps, self.total_frames, track_id, speaker)

    def _track_id_for_speaker(self, speaker: str) -> int:
        speaker = str(speaker or "").strip()
        for track_id, mapped_speaker in self.yolo_id_to_speaker.items():
            if str(mapped_speaker).strip() == speaker:
                return int(track_id)
        return 1

    def _pre_scan_dummy_box(self, frame_width: int, frame_height: int, track_id: int) -> dict:
        position = self.get_person_bubble_style(track_id).get("position", "auto")
        if position == "auto":
            position = self.default_bubble_position(track_id)
        if position == "bottom":
            cx, cy = frame_width * 0.5, frame_height * 0.18
        elif position == "left":
            cx, cy = frame_width * 0.76, frame_height * 0.50
        elif position == "right":
            cx, cy = frame_width * 0.24, frame_height * 0.50
        else:
            cx, cy = frame_width * 0.5, frame_height * 0.78
        half_w = min(frame_width * 0.10, 120)
        half_h = min(frame_height * 0.05, 60)
        return {
            "id": int(track_id),
            "bbox": (
                int(max(0, cx - half_w)),
                int(max(0, cy - half_h)),
                int(min(frame_width - 1, cx + half_w)),
                int(min(frame_height - 1, cy + half_h)),
            ),
        }

    def set_cut_ranges(self, ranges):
        self.cut_ranges = normalize_time_ranges(ranges)

    def _frame_in_cut_ranges(self, frame_idx: int, fps: float) -> bool:
        seconds = (frame_idx - 1) / max(fps or 30, 1)
        return any(start <= seconds < end for start, end in self.cut_ranges)

    def get_preview_frame(self, frame_idx: int):
        if not self.video_path:
            return None
        with self._preview_lock:
            return self._get_preview_frame_locked(frame_idx)

    def _get_preview_frame_locked(self, frame_idx: int):
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
        if boxes:
            for box_data in boxes:
                text = self._text_for_track(frame_idx, box_data["id"])
                self.draw_speech_bubble(frame, text, box_data["id"], boxes)
        elif not self.tracking_data and self.data_processor.has_data():
            # 尚未掃描：在畫面下方以字幕方式預覽對話文字
            row_idx, text = self.data_processor.find_dialogue_at_time(frame_idx, self.fps)
            if text:
                fh, fw = frame.shape[:2]
                speaker, _ = self.data_processor.get_dialogue_row_values(row_idx)
                track_id = self._track_id_for_speaker(speaker)
                dummy_box = self._pre_scan_dummy_box(fw, fh, track_id)
                self.draw_speech_bubble(frame, text, track_id, [dummy_box], draw_connector=False)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return self._resize_preview(rgb)

    def _resize_preview(self, rgb):
        h, w = rgb.shape[:2]
        scale = min(MAX_PREVIEW_SIZE / max(w, 1), MAX_PREVIEW_SIZE / max(h, 1), 1.0)
        if scale < 1.0:
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
        return rgb

    # ------------------------------------------------------------------ 匯出
    def export_video(self, preview: bool = False):
        if not self.video_path or not self.tracking_data:
            return
        self.is_processing = True
        export_source_path = self.video_path if preview else (self.source_video_path or self.video_path)
        safe_path = get_safe_path(export_source_path)
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
        proxy_width = max(1, int(width if preview else (self.video_width or width)))
        proxy_height = max(1, int(height if preview else (self.video_height or height)))
        scale_x = width / proxy_width
        scale_y = height / proxy_height

        base_video_path = self.source_video_path or self.video_path
        suffix = "_hud_preview.mp4" if preview else "_hud_output.mp4"
        out_base_path = os.path.splitext(base_video_path)[0] + suffix
        real_out_path = out_base_path if preview else available_output_path(out_base_path)
        if preview and os.path.exists(real_out_path):
            try:
                os.remove(real_out_path)
            except OSError:
                pass
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
        original_font_size = self.style.get("font_size", 72)
        original_offsets = dict(self.bubble_offsets)
        render_scale = (scale_x + scale_y) / 2
        try:
            if abs(render_scale - 1.0) > 0.01:
                self.style["font_size"] = max(1, int(round(int(original_font_size) * render_scale)))
                self.bubble_offsets = {
                    tid: (int(round(dx * scale_x)), int(round(dy * scale_y)))
                    for tid, (dx, dy) in original_offsets.items()
                }
                self.bubble_cache.clear()
            while cap.isOpened() and self.is_processing:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_count += 1
                if self._frame_in_cut_ranges(frame_count, fps):
                    if self.ui_callback and frame_count % 10 == 0:
                        self.ui_callback("progress", min(frame_count / max(total, 1), 1.0))
                    continue
                boxes = self._scale_tracking_boxes(self.tracking_data.get(frame_count, []), scale_x, scale_y)
                for box_data in boxes:
                    text = self._text_for_track(frame_count, box_data["id"])
                    self.draw_speech_bubble(frame, text, box_data["id"], boxes)
                out.write(frame)
                if self.ui_callback and frame_count % 10 == 0:
                    self.ui_callback("progress", min(frame_count / max(total, 1), 1.0))
        finally:
            self.style["font_size"] = original_font_size
            self.bubble_offsets = original_offsets
            self.bubble_cache.clear()
            cap.release()
            out.release()
            duration = total / max(fps, 1)
            audio_source_path = get_safe_path(self.source_video_path or self.video_path)
            self._merge_audio_or_move(safe_out_path, audio_source_path, real_out_path, duration)
            self.is_processing = False
            if self.ui_callback:
                self.ui_callback("finished", 1.0, out_path=real_out_path)

    def _scale_tracking_boxes(self, boxes: list, scale_x: float, scale_y: float) -> list:
        if abs(scale_x - 1.0) <= 0.01 and abs(scale_y - 1.0) <= 0.01:
            return boxes
        scaled = []
        for box in boxes:
            x1, y1, x2, y2 = box["bbox"]
            scaled.append({
                **box,
                "bbox": (
                    int(round(x1 * scale_x)),
                    int(round(y1 * scale_y)),
                    int(round(x2 * scale_x)),
                    int(round(y2 * scale_y)),
                ),
            })
        return scaled

    def _merge_audio_or_move(self, video_path: str, source_path: str, output_path: str, duration: float | None = None):
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
                    cmd = [ffmpeg, "-y", "-i", video_path, "-c:v", "copy", "-an", temp_audio_out]
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
                    msg = detail[-1] if detail else "ffmpeg 未回傳詳細錯誤。"
                    self.ui_callback("error_log", f"音訊合併失敗，將輸出無音訊影片：{msg}")
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
