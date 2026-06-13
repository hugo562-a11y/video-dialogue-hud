"""WaveformMixin — 聲波繪製、縮放、拖曳與時間軸互動。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import numpy as np
import pandas as pd

from core.constants import SILENCE_SPEAKER, get_safe_path
from core.utils import parse_time_range, frame_to_seconds, seconds_to_frame


class WaveformMixin:

    # ------------------------------------------------------------------ 生成
    def _generate_waveform(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not self.renderer.video_path:
            return
        self._clear_waveform_audio_cache()
        fd, wav_path = tempfile.mkstemp(suffix="_waveform.wav")
        os.close(fd)
        # Keep the calibration workspace on one timeline: waveform, speech,
        # preview video, and scrub audio all use the proxy video.
        source_path = self.renderer.video_path
        cmd = [
            ffmpeg, "-y", "-v", "error", "-i", get_safe_path(source_path),
            "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", wav_path
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    startupinfo=startupinfo, timeout=90)
            if result.returncode != 0 or not os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
                return
            # Read WAV directly via Python (was: second ffmpeg subprocess)
            import wave
            with wave.open(wav_path, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
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
        return [(round(s, 3), round(e, 3)) for s, e in merged if e - s >= min_active]

    # ------------------------------------------------------------------ 視圖
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

    def schedule_waveform_refresh(self, delay_ms: int = 160):
        after_id = getattr(self, "_waveform_refresh_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._waveform_refresh_after_id = self.after(delay_ms, self._run_waveform_refresh)

    def _run_waveform_refresh(self):
        self._waveform_refresh_after_id = None
        self.draw_waveform(self.current_frame())

    # ------------------------------------------------------------------ 繪製
    def draw_waveform(self, playhead_frame=None):
        if not hasattr(self, "waveform_canvas"):
            return
        canvas = self.waveform_canvas
        canvas.delete("all")
        self._waveform_playhead_id = None
        w = max(1, canvas.winfo_width() or 800)
        h = max(1, canvas.winfo_height() or 58)
        samples = self.waveform_samples
        if samples is None or len(samples) == 0:
            canvas.create_text(w // 2, h // 2, text="聲波載入中", fill="#AAAAAA")
            return
        self.waveform_dialogue_handles = []
        wave_top = 18
        hz = h - wave_top
        mid = wave_top + hz // 2
        count = len(samples)
        view_start, view_end = self.get_waveform_view_range()
        view_span = max(view_end - view_start, 0.001)
        # --- draw waveform as a single PIL image (was 800+ per-pixel canvas lines) ---
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (w, hz))
        draw = ImageDraw.Draw(img)
        color = (56, 189, 248, 255)
        mid_pil = hz // 2
        for x in range(w):
            seconds = view_start + (x / max(1, w - 1)) * view_span
            idx = int(seconds / max(self.waveform_step_seconds, 1e-6))
            if idx < 0 or idx >= count:
                continue
            amp = float(samples[idx]) * (hz * 0.42)
            draw.line([(x, mid_pil - amp), (x, mid_pil + amp)], fill=color)
        from PIL import ImageTk
        self._waveform_image = ImageTk.PhotoImage(img)
        canvas.create_image(0, wave_top, anchor="nw", image=self._waveform_image)
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
            self._waveform_playhead_id = canvas.create_line(px, 0, px, h, fill="#46A3FF", width=2)

    def update_waveform_playhead(self, playhead_frame):
        if not hasattr(self, "waveform_canvas") or not self.renderer.total_frames:
            return
        canvas = self.waveform_canvas
        w = max(1, canvas.winfo_width() or 800)
        h = max(1, canvas.winfo_height() or 58)
        seconds = frame_to_seconds(playhead_frame, self.renderer.fps)
        px = max(0, min(w, self.seconds_to_waveform_x(seconds, w)))
        playhead_id = getattr(self, "_waveform_playhead_id", None)
        if playhead_id is not None:
            try:
                canvas.coords(playhead_id, px, 0, px, h)
                return
            except Exception:
                pass
        self._waveform_playhead_id = canvas.create_line(px, 0, px, h, fill="#46A3FF", width=2)

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
            is_deleted = dp.is_deleted(row_idx)
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
            speaker_bg, speaker_accent = self.speaker_palette(speaker, row_idx) if hasattr(self, "speaker_palette") else ("#2D2D2D", "#46A3FF")
            fill = "#5D2630" if is_deleted else ("#3D3D3D" if is_selected else speaker_bg)
            outline = "#E74C3C" if is_deleted else ("#46A3FF" if is_selected else speaker_accent)
            width_px = 2 if is_selected else 1
            canvas.create_rectangle(draw_x, 18, draw_x2, height, fill=fill, stipple="gray25", outline="")
            canvas.create_rectangle(draw_x, 18, draw_x2, height, outline=outline, width=width_px)
            if 0 <= x <= width:
                canvas.create_rectangle(max(0, x - 1), 18, min(width, x + 1), height, fill="#2ECC71", outline="")
            if 0 <= x2 <= width:
                canvas.create_rectangle(max(0, x2 - 1), 18, min(width, x2 + 1), height, fill="#E74C3C", outline="")
            self.waveform_dialogue_handles.append({
                "row_idx": row_idx, "start": start, "end": end, "x1": x, "x2": x2,
            })
            label_x = max(0, min(width - 1, x))
            if label_x - last_x < 28:
                continue
            last_x = label_x
            label = "剪" if is_deleted else text[:3]
            label_color = "#E74C3C" if is_deleted else ("#46A3FF" if is_selected else speaker_accent)
            canvas.create_text(
                label_x + 3, 4, anchor="nw", text=label, fill=label_color,
                font=("Microsoft JhengHei UI", 9, "bold" if is_selected else "normal"),
            )

    # ------------------------------------------------------------------ 座標
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

    # ------------------------------------------------------------------ 命中測試
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

    # ------------------------------------------------------------------ 拖曳更新
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
        self.update_script_row_time_display(row_idx)
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
        self.update_script_row_time_display(row_idx)
        frame = seconds_to_frame(new_start, self.renderer.fps, self.renderer.total_frames)
        self.slider_timeline.set(frame)
        self.update_timecode_and_waveform(frame)
        self._render_scrub(frame)
        return frame

    # ------------------------------------------------------------------ 跳轉
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

    # ------------------------------------------------------------------ 事件
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
            self.update_script_selection_styles()
            self._scroll_to_selected_row()
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
            self.select_dialogue_row(range_hit["row_idx"], seek=True)
            self._waveform_range_drag_start = {
                "mouse_seconds": self._seconds_from_waveform_x(event.x),
                "start": range_hit["start"],
                "end": range_hit["end"],
            }
            self.waveform_canvas.configure(cursor="fleur")
            return
        self._waveform_drag_mode = None
        self.seek_to_frame(self._frame_from_waveform_x(event.x), play_sound=False)

    def on_waveform_drag(self, event):
        self._waveform_drag_moved = True
        if self.waveform_drag_handle:
            if self._waveform_drag_mode == "range":
                self.update_waveform_range_drag(event.x)
            else:
                self.update_waveform_time_handle(event.x)

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
        # 純點擊無拖曳 → 不修改資料、不播放聲音
        if not self._waveform_drag_moved:
            self.waveform_drag_handle = None
            self._waveform_drag_mode = None
            self._waveform_range_drag_start = None
            self._waveform_undo_pushed = False
            self.waveform_canvas.configure(cursor="")
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
        self.update_script_selection_styles()
        self._scroll_to_selected_row()
        self.update_current_sentence_label()
        if frame is not None and self.audio_scrub_var.get():
            self.play_audio_preview(frame, duration=0.35, force=True)

    def on_waveform_motion(self, event):
        if self.waveform_drag_handle:
            self.waveform_canvas.configure(
                cursor="fleur" if self._waveform_drag_mode == "range" else "sb_h_double_arrow"
            )
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

    # ------------------------------------------------------------------ 鍵盤導航
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

    def seek_home(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        self.seek_to_frame(1, play_sound=False)
        return "break"

    def seek_end(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        total = max(1, int(self.renderer.total_frames or 1))
        self.seek_to_frame(total, play_sound=False)
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
        self.start_preview_range(start, end)
        return "break"
