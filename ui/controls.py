"""ControlsMixin — Undo/Redo、播放、音訊、日誌、佇列、時間軸。"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import io
import wave

import cv2
from PIL import Image

from core.constants import get_safe_path
from core.utils import frame_to_seconds, seconds_to_frame


class ControlsMixin:

    # ------------------------------------------------------------------ Undo/Redo
    def snapshot_state(self, label=""):
        dp = self.renderer.data_processor
        return {
            "label": label,
            "df": None if dp.df is None else dp.df.copy(deep=True),
            "df_path": dp.path,
            "cut_ranges": list(self.renderer.cut_ranges),
            "speakers": dict(self.renderer.yolo_id_to_speaker),
            "person_styles": {tid: dict(style) for tid, style in self.renderer.person_styles.items()},
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
        if hasattr(dp, "invalidate_cache"):
            dp.invalidate_cache()
        self.renderer.set_cut_ranges(state.get("cut_ranges", []))
        self.renderer.yolo_id_to_speaker = dict(state.get("speakers", {}))
        self.renderer.person_styles = {tid: dict(style) for tid, style in state.get("person_styles", {}).items()}
        self.renderer.bubble_offsets = dict(state.get("bubble_offsets", {}))
        self.selected_dialogue_row = state.get("selected_row")
        self.renderer.bubble_cache.clear()
        self.end_text_undo_group()
        self.refresh_after_state_restore()

    def refresh_after_state_restore(self):
        self.btn_scan.configure(
            state="normal" if self.people_count_confirmed and self.renderer.data_processor.has_data() else "disabled"
        )
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

    # ------------------------------------------------------------------ 播放
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

    def start_preview_playback(self, play_edited=False):
        if self.preview_playing:
            return
        fps = self.renderer.fps or 30
        start_frame = int(float(self.slider_timeline.get()))
        plan = self._build_playback_plan(start_frame, play_edited)
        if not plan:
            self.log("沒有可播放的片段。")
            return
        first_source_second = plan[0]["source_start"]
        start_frame = seconds_to_frame(first_source_second, fps, self.renderer.total_frames)
        self.preview_playing = True
        self._play_timeline_plan = plan
        self._play_duration = plan[-1]["play_end"]
        self._preview_play_start_frame = start_frame
        self._last_playback_frame = None
        self._play_current_segment_index = None
        self._play_seq_cap = None
        self._play_seq_idx = start_frame
        if self.renderer.video_path:
            cap = cv2.VideoCapture(get_safe_path(self.renderer.video_path))
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start_frame - 1))
                self._play_seq_cap = cap

        self.slider_timeline.set(start_frame)
        self.update_timecode_and_waveform(start_frame)
        self.sync_fields_for_frame(start_frame)
        self._preview_play_start_time = self.start_preview_audio(plan)
        self._last_playback_ui_sync_time = 0.0
        self._last_playback_waveform_time = 0.0
        self._last_preview_render_request_time = 0.0
        self._play_preview_step()

    def start_preview_range(self, start_seconds: float, end_seconds: float):
        if not self.renderer.video_path or not self.renderer.fps:
            return
        start_seconds = max(0.0, float(start_seconds))
        end_seconds = max(start_seconds, float(end_seconds))
        if end_seconds <= start_seconds + 0.01:
            return
        if self.preview_playing:
            self.stop_preview_playback()

        fps = self.renderer.fps or 30
        start_frame = seconds_to_frame(start_seconds, fps, self.renderer.total_frames)
        self.preview_playing = True
        self._play_timeline_plan = [{
            "source_start": start_seconds,
            "source_end": end_seconds,
            "play_start": 0.0,
            "play_end": end_seconds - start_seconds,
        }]
        self._play_duration = end_seconds - start_seconds
        self._preview_play_start_frame = start_frame
        self._last_playback_frame = None
        self._play_current_segment_index = None
        self._play_seq_cap = None
        self._play_seq_idx = start_frame
        cap = cv2.VideoCapture(get_safe_path(self.renderer.video_path))
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start_frame - 1))
            self._play_seq_cap = cap

        self.slider_timeline.set(start_frame)
        self.update_timecode_and_waveform(start_frame)
        self.sync_fields_for_frame(start_frame)
        self.play_audio_preview_at_seconds(start_seconds, duration=end_seconds - start_seconds, force=True, use_cache=False)
        self._preview_play_start_time = time.perf_counter()
        self._last_playback_ui_sync_time = 0.0
        self._last_playback_waveform_time = 0.0
        self._last_preview_render_request_time = 0.0
        self._play_preview_step()

    def stop_preview_playback(self):
        self.preview_playing = False
        self._play_timeline_plan = None
        self._play_duration = 0.0
        cap = getattr(self, "_play_seq_cap", None)
        if cap is not None:
            cap.release()
            self._play_seq_cap = None
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
        fps   = max(self.renderer.fps or 30, 1)
        elapsed = max(0.0, time.perf_counter() - self._preview_play_start_time)
        duration = max(0.0, float(getattr(self, "_play_duration", 0.0) or 0.0))
        if duration and elapsed >= duration:
            self.stop_preview_playback()
            return

        segment_index, source_seconds = self._play_position_for_elapsed(elapsed)
        actual_frame = seconds_to_frame(source_seconds, fps, self.renderer.total_frames)
        cv_frame = self._read_playback_frame(actual_frame, segment_index)
        if not self.preview_playing:
            return
        now = time.perf_counter()
        sync_ui = now - getattr(self, "_last_playback_ui_sync_time", 0.0) >= 0.10
        if sync_ui:
            self.slider_timeline.set(actual_frame)
            self.update_timecode_and_waveform(actual_frame, draw_waveform=False)
            if hasattr(self, "update_waveform_playhead"):
                self.update_waveform_playhead(actual_frame)
            self._last_playback_ui_sync_time = now
            self.sync_fields_for_frame(actual_frame)

        render_interval = 1.0 / 18.0
        can_render = now - getattr(self, "_last_preview_render_request_time", 0.0) >= render_interval
        if cv_frame is not None and can_render and actual_frame != getattr(self, "_last_playback_frame", None) and not self._preview_render_pending:
            self._last_playback_frame = actual_frame
            self._last_preview_render_time = now
            self._last_preview_render_request_time = now
            self._render_play_frame(cv_frame, actual_frame)

        delay_ms = max(8, int(1000 / min(fps, 60)))
        self._preview_play_after_id = self.after(delay_ms, self._play_preview_step)

    def _build_playback_plan(self, start_frame: int, play_edited: bool) -> list[dict]:
        fps = self.renderer.fps or 30
        total_duration = self.get_waveform_timeline_duration() if hasattr(self, "get_waveform_timeline_duration") else 0.0
        if not total_duration and self.renderer.total_frames:
            total_duration = self.renderer.total_frames / max(fps, 1)
        start_seconds = frame_to_seconds(start_frame, fps)
        if not play_edited:
            if total_duration <= start_seconds:
                return []
            return [{
                "source_start": start_seconds,
                "source_end": total_duration,
                "play_start": 0.0,
                "play_end": total_duration - start_seconds,
            }]

        kept = self.renderer.data_processor.get_kept_time_ranges()
        segments = []
        cursor = 0.0
        for start, end in kept:
            if end <= start_seconds:
                continue
            source_start = max(start, start_seconds)
            source_end = min(end, total_duration) if total_duration else end
            if source_end <= source_start:
                continue
            length = source_end - source_start
            segments.append({
                "source_start": source_start,
                "source_end": source_end,
                "play_start": cursor,
                "play_end": cursor + length,
            })
            cursor += length
        return segments

    def _source_seconds_for_play_elapsed(self, elapsed: float) -> float:
        return self._play_position_for_elapsed(elapsed)[1]

    def _play_position_for_elapsed(self, elapsed: float) -> tuple[int | None, float]:
        plan = getattr(self, "_play_timeline_plan", None) or []
        if not plan:
            return None, frame_to_seconds(self._preview_play_start_frame, self.renderer.fps)
        for index, segment in enumerate(plan):
            if elapsed < segment["play_end"] or index == len(plan) - 1:
                return index, segment["source_start"] + max(0.0, elapsed - segment["play_start"])
        return len(plan) - 1, plan[-1]["source_end"]

    def _read_playback_frame(self, target_frame: int, segment_index: int | None):
        cap = getattr(self, "_play_seq_cap", None)
        if cap is None or not cap.isOpened():
            return None
        target_frame = max(1, int(target_frame))
        segment_changed = segment_index != getattr(self, "_play_current_segment_index", None)
        current_idx = int(getattr(self, "_play_seq_idx", target_frame))
        gap = target_frame - current_idx
        if segment_changed or gap < 0 or gap > 4:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, target_frame - 1))
            current_idx = target_frame
            self._play_seq_idx = target_frame
            self._play_current_segment_index = segment_index

        cv_frame = None
        while current_idx <= target_frame:
            ret, frame = cap.read()
            if not ret:
                self.stop_preview_playback()
                return None
            cv_frame = frame
            current_idx += 1
        self._play_seq_idx = current_idx
        return cv_frame

    def _render_play_frame(self, cv_frame, frame_idx):
        self._preview_render_pending = True
        self._preview_request_id += 1
        request_id = self._preview_request_id

        def worker():
            try:
                img = self.renderer.render_frame_with_bubbles(cv_frame, frame_idx)
                if img is None:
                    self.ui_queue.put({"type": "preview_done", "request_id": request_id})
                    return
                self.ui_queue.put({
                    "type": "preview",
                    "request_id": request_id,
                    "img": img,
                    "boxes": self.renderer.tracking_data.get(frame_idx, []),
                })
            except Exception:
                self.ui_queue.put({"type": "preview_done", "request_id": request_id})

        threading.Thread(target=worker, daemon=True).start()

    def start_preview_audio(self, plan=None):
        if not self.renderer.video_path or not self.renderer.fps:
            return time.perf_counter()
        plan = plan or self._build_playback_plan(int(float(self.slider_timeline.get())), False)
        if self._start_winsound_timeline(plan):
            return time.perf_counter()
        ffplay = shutil.which("ffplay")
        if not ffplay:
            self.log("找不到 ffplay，預覽播放只有畫面沒有聲音。")
            return time.perf_counter()
        try:
            frame_idx = int(float(self.slider_timeline.get()))
        except Exception:
            frame_idx = 1
        seconds = plan[0]["source_start"] if plan else frame_to_seconds(frame_idx, self.renderer.fps)
        self.stop_audio_preview()
        timeline_audio_path = self._write_timeline_wav_file(plan)
        if timeline_audio_path:
            self._timeline_audio_path = timeline_audio_path
            cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-vn", timeline_audio_path]
        else:
            cmd = [
                ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-vn",
                "-ss", f"{seconds:.2f}",
                self._audio_preview_source(),
            ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            self._ffplay_process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo,
            )
            return time.perf_counter()
        except Exception:
            self._ffplay_process = None
            return time.perf_counter()

    def _start_winsound_timeline(self, plan) -> bool:
        if os.name != "nt" or not plan:
            return False
        wav_path = getattr(self, "_waveform_audio_path", None)
        if not wav_path or not os.path.exists(wav_path):
            return False
        try:
            import winsound
            wav_bytes = self._timeline_wav_bytes(plan)
            if not wav_bytes:
                return False
            self.stop_audio_preview()
            temp_path = self._write_temp_wav_bytes(wav_bytes)
            if not temp_path:
                return False
            self._timeline_audio_path = temp_path
            winsound.PlaySound(temp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception:
            return False

    def _write_timeline_wav_file(self, plan) -> str | None:
        try:
            wav_bytes = self._timeline_wav_bytes(plan)
            return self._write_temp_wav_bytes(wav_bytes) if wav_bytes else None
        except Exception:
            return None

    def _write_temp_wav_bytes(self, wav_bytes: bytes) -> str | None:
        fd, temp_path = tempfile.mkstemp(suffix="_preview_timeline.wav")
        os.close(fd)
        try:
            with open(temp_path, "wb") as handle:
                handle.write(wav_bytes)
            return temp_path
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return None

    def _timeline_wav_bytes(self, plan) -> bytes | None:
        wav_path = getattr(self, "_waveform_audio_path", None)
        if not wav_path:
            return None
        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            total = wf.getnframes()
            chunks = []
            for segment in plan:
                start = max(0, min(total, int(segment["source_start"] * sr)))
                end = max(start, min(total, int(segment["source_end"] * sr)))
                if end <= start:
                    continue
                wf.setpos(start)
                chunks.append(wf.readframes(end - start))
        if not chunks:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out_wf:
            out_wf.setnchannels(ch)
            out_wf.setsampwidth(sw)
            out_wf.setframerate(sr)
            for chunk in chunks:
                out_wf.writeframes(chunk)
        return buf.getvalue()

    def _write_audio_clip_file(self, seconds: float, duration: float) -> str | None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        fd, temp_path = tempfile.mkstemp(suffix="_preview_clip.wav")
        os.close(fd)
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-i", self._audio_preview_source(),
            "-ss", f"{seconds:.3f}",
            "-t", f"{duration:.3f}",
            "-vn", "-ac", "2", "-ar", "44100",
            "-acodec", "pcm_s16le",
            temp_path,
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo, timeout=20,
            )
            if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 44:
                return temp_path
        except Exception:
            pass
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return None

    # ------------------------------------------------------------------ 音訊
    def play_audio_preview(self, frame_idx, duration=0.35, force=False):
        if not self.renderer.video_path or not self.renderer.fps:
            return
        seconds = frame_to_seconds(frame_idx, self.renderer.fps)
        self.play_audio_preview_at_seconds(seconds, duration=duration, force=force)

    def play_audio_preview_at_seconds(self, seconds, duration=0.35, force=False, use_cache=True):
        if not self.renderer.video_path:
            return
        seconds = max(0.0, float(seconds))
        duration = max(0.01, float(duration))
        if not force and abs(seconds - self._last_audio_preview_at) < 0.12:
            return
        self._last_audio_preview_at = seconds
        self.stop_audio_preview()

        # Fast path: play in-memory WAV clip from pre-extracted waveform audio.
        # winsound has near-zero startup latency vs ~150ms for a new ffplay process.
        wav_path = getattr(self, "_waveform_audio_path", None) if use_cache else None
        if wav_path and os.path.exists(wav_path) and os.name == "nt":
            try:
                import wave, winsound, io
                with wave.open(wav_path, "rb") as wf:
                    sr  = wf.getframerate()
                    ch  = wf.getnchannels()
                    sw  = wf.getsampwidth()
                    tot = wf.getnframes()
                    start_s = max(0, min(int(seconds * sr), tot))
                    n_s     = min(int(duration * sr), tot - start_s)
                    if n_s <= 0:
                        return
                    wf.setpos(start_s)
                    raw = wf.readframes(n_s)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as out_wf:
                    out_wf.setnchannels(ch)
                    out_wf.setsampwidth(sw)
                    out_wf.setframerate(sr)
                    out_wf.writeframes(raw)
                winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY | winsound.SND_ASYNC)
                return
            except Exception:
                pass  # fall through to ffplay

        clip_path = self._write_audio_clip_file(seconds, duration) if not use_cache else None
        if clip_path:
            self._timeline_audio_path = clip_path
            if os.name == "nt":
                try:
                    import winsound
                    winsound.PlaySound(clip_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
                except Exception:
                    pass
            ffplay = shutil.which("ffplay")
            if not ffplay:
                return
            cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-vn", clip_path]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                self._ffplay_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo,
                )
                return
            except Exception:
                self._ffplay_process = None

        ffplay = shutil.which("ffplay")
        if not ffplay:
            return
        cmd = [
            ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-vn",
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
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo,
            )
        except Exception:
            self._ffplay_process = None
            self.log("音訊預覽播放失敗。")

    def _audio_preview_source(self):
        source_path = self.renderer.video_path
        return get_safe_path(source_path)

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
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        proc = self._ffplay_process
        self._ffplay_process = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        timeline_audio_path = getattr(self, "_timeline_audio_path", None)
        self._timeline_audio_path = None
        if timeline_audio_path:
            try:
                if os.path.exists(timeline_audio_path):
                    os.remove(timeline_audio_path)
            except OSError:
                pass

    # ------------------------------------------------------------------ 日誌
    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.status_label.configure(text=text)

    # Disable keyboard editing in log_box while still allowing text selection

    def toggle_log_panel(self):
        if self._log_expanded:
            self.log_box.pack_forget()
            self.btn_toggle_log.configure(text="顯示記錄")
            self._log_expanded = False
        else:
            self.log_box.pack(fill="x", padx=12, pady=(4, 12), before=self.btn_toggle_log)
            self.btn_toggle_log.configure(text="隱藏記錄")
            self._log_expanded = True

    # ------------------------------------------------------------------ 佇列
    def check_queue(self):
        try:
            while True:
                try:
                    msg = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if msg["type"] == "progress":
                        val = msg["value"]
                        self.progress_bar.set(val)
                        if hasattr(self, "lbl_progress"):
                            if val >= 1.0:
                                self.lbl_progress.configure(text="")
                            else:
                                pct = min(100, max(0, int(val * 100)))
                                desc = msg.get("text", "")
                                self.lbl_progress.configure(text=f"{desc}{pct}%")
                    elif msg["type"] == "scan_finished":
                        self.on_scan_finished()
                    elif msg["type"] == "finished":
                        self.on_export_finished(msg["out_path"])
                    elif msg["type"] == "proxy_done":
                        self.on_proxy_done(msg["source_path"], msg["proxy_path"])
                    elif msg["type"] == "preview":
                        if msg.get("request_id") != self._preview_request_id:
                            continue
                        self._preview_render_pending = False
                        self.preview_boxes = msg.get("boxes", [])
                        self.set_preview_image(Image.fromarray(msg["img"]), reset_view=False)
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
                except Exception as exc:
                    import traceback
                    self.log(f"[UI 錯誤] {exc}\n{traceback.format_exc()}")
                    if msg.get("type") == "speech_done":
                        self.on_worker_error(f"載入語音腳本失敗：{exc}")
        except Exception:
            pass
        delay_ms = 16 if getattr(self, "preview_playing", False) else 100
        self.after(delay_ms, self.check_queue)

    def handle_renderer_update(self, msg_type, value, preview_img=None, out_path=None):
        if msg_type == "progress":
            self.ui_queue.put({"type": "progress", "value": value})
        elif msg_type == "scan_finished":
            self.ui_queue.put({"type": "scan_finished"})
        elif msg_type == "finished":
            self.ui_queue.put({"type": "finished", "out_path": out_path})
        elif msg_type == "error_log":
            self.ui_queue.put({"type": "error_log", "text": value})

    # ------------------------------------------------------------------ 設定
    def update_settings(self):
        try:
            tid = int(self.entry_id.get())
        except ValueError:
            return
        if self._loading_person_fields:
            return
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
            if hasattr(self, "update_current_sentence_label"):
                self.update_current_sentence_label()
            if hasattr(self, "schedule_script_preview_refresh"):
                self.schedule_script_preview_refresh(delay_ms=450)

    def update_style(self, _event=None):
        self.renderer.style["font_size"] = int(self.slider_font_size.get())
        self.renderer.bubble_cache.clear()
        if self.slider_timeline.cget("state") == "normal":
            self.on_timeline_scrub(self.slider_timeline.get())

    # ------------------------------------------------------------------ 時間軸
    def on_timeline_scrub(self, value):
        frame_idx = max(1, int(float(value)))
        if self.preview_playing:
            self.stop_preview_playback()
        self.update_timecode_and_waveform(frame_idx)
        self.sync_fields_for_frame(frame_idx)
        if hasattr(self, "_scrub_after_id"):
            self.after_cancel(self._scrub_after_id)
        self._scrub_after_id = self.after(80, lambda: self._render_scrub(frame_idx))

    def _on_slider_press(self, event):
        self._slider_was_dragged = False

    def _on_slider_drag(self, event):
        self._slider_was_dragged = True

    def _on_slider_release(self, event):
        if not self._slider_was_dragged and self.slider_timeline.cget("state") == "normal":
            self.toggle_preview_playback()

    def _toggle_person_boxes(self):
        self._show_person_boxes = not getattr(self, "_show_person_boxes", True)
        if hasattr(self, "btn_toggle_boxes"):
            self.btn_toggle_boxes.configure(
                text="顯示人物框" if not self._show_person_boxes else "隱藏人物框"
            )
        self._refresh_canvas()

    def _toggle_adjust_box_mode(self):
        if self._canvas_mode == "adjust_box":
            self._canvas_mode = "pan"
            self.preview_canvas.configure(cursor="crosshair")
            if hasattr(self, "btn_adjust_boxes"):
                self.log("已結束調整框位模式。")
        else:
            self._canvas_mode = "adjust_box"
            self._adjust_box_drag_tid = None
            self.preview_canvas.configure(cursor="crosshair")
            if hasattr(self, "btn_adjust_boxes"):
                self.btn_adjust_boxes.configure(fg_color="#555555", hover_color="#666666")
            self.log("調整框位模式：拖曳人物框可修正位置，完成後再按一次結束。")

    def _set_play_buttons_state(self, state: str):
        if hasattr(self, "btn_play_all"):
            self.btn_play_all.configure(state=state)
        if hasattr(self, "btn_play_edited"):
            self.btn_play_edited.configure(state=state)

    def update_timecode_and_waveform(self, frame_idx, draw_waveform=True):
        fps = self.renderer.fps
        if fps:
            seconds = int(frame_to_seconds(frame_idx, fps))
            mm, ss = divmod(seconds, 60)
            hh, mm = divmod(mm, 60)
            self.lbl_timecode.configure(text=f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}")
        if hasattr(self, "lbl_duration_info"):
            self.lbl_duration_info.configure(text=self._duration_info_text(frame_idx))
        if draw_waveform:
            self.draw_waveform(frame_idx)

    def _duration_info_text(self, frame_idx=None) -> str:
        fps   = self.renderer.fps or 30
        total = self.renderer.total_frames or 0
        if not total:
            return ""
        total_secs = total / fps

        dp = self.renderer.data_processor
        if dp.has_data():
            kept = dp.get_kept_time_ranges()
            edited_secs = sum(max(0.0, e - s) for s, e in kept)
        else:
            edited_secs = total_secs

        def fmt(s: float) -> str:
            s = int(s)
            mm, ss = divmod(s, 60)
            hh, mm = divmod(mm, 60)
            return f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"

        if frame_idx and fps:
            cur = fmt(frame_to_seconds(frame_idx, fps))
        else:
            cur = "00:00"
        return f"{cur}  |  剪後 {fmt(edited_secs)}  |  全長 {fmt(total_secs)}"

    def _render_scrub(self, frame_idx):
        self._preview_render_pending = True
        self._preview_request_id += 1
        request_id = self._preview_request_id

        def worker():
            try:
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
            except Exception as exc:
                import traceback
                self.ui_queue.put({"type": "error_log", "text": f"[渲染錯誤] {exc}\n{traceback.format_exc()}"})
                self.ui_queue.put({"type": "preview_done", "request_id": request_id})

        threading.Thread(target=worker, daemon=True).start()

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
            frame_idx, self.renderer.fps, current_tid, speaker,
        )
        if row_idx is None and not strict_current_id:
            row_idx, text = self.renderer.data_processor.find_dialogue_at_time(
                frame_idx, self.renderer.fps,
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
        matched_tid_text = str(matched_tid)
        if self.entry_id.get() != matched_tid_text:
            self.entry_id.delete(0, "end")
            self.entry_id.insert(0, matched_tid_text)
        speaker_text = row_speaker or speaker
        if self.entry_speaker.get() != speaker_text:
            self.entry_speaker.delete(0, "end")
            self.entry_speaker.insert(0, speaker_text)
        try:
            _focused = self.focus_get()
            _inner = getattr(self.entry_text, "_entry", None)
            _typing = _focused is not None and (_focused is _inner or _focused is self.entry_text)
        except Exception:
            _typing = False
        if not _typing and self.entry_text.get() != (row_text or text):
            self.entry_text.delete(0, "end")
            self.entry_text.insert(0, row_text or text)
        self._loading_person_fields = False
        if previous_row != self.selected_dialogue_row:
            self.update_script_selection_styles({previous_row, self.selected_dialogue_row})
            if getattr(self, "preview_playing", False):
                return
            if hasattr(self, "_sync_scroll_after_id"):
                try:
                    self.after_cancel(self._sync_scroll_after_id)
                except Exception:
                    pass
            self._sync_scroll_after_id = self.after(180, self._scroll_to_selected_row)

    # ------------------------------------------------------------------ 關閉
    def on_close(self):
        self.stop_preview_playback()
        self.stop_audio_preview()
        after_id = getattr(self, "_script_preview_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
            self._script_preview_after_id = None
        waveform_after_id = getattr(self, "_waveform_refresh_after_id", None)
        if waveform_after_id is not None:
            try:
                self.after_cancel(waveform_after_id)
            except Exception:
                pass
            self._waveform_refresh_after_id = None
        self._clear_waveform_audio_cache()
        self._cleanup_proxy_video()
        self.destroy()
