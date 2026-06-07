"""ControlsMixin — Undo/Redo、播放、音訊、日誌、佇列、時間軸。"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time

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
        self._play_edited = play_edited
        if play_edited:
            # 即時計算剪切範圍，不需等到匯出才有 cut_ranges
            self.renderer.set_cut_ranges(
                self.renderer.data_processor.get_export_cut_ranges(self.get_video_duration())
            )
        self.preview_playing = True
        start_frame = int(float(self.slider_timeline.get()))
        self._preview_play_start_frame = start_frame

        # 開一個獨立的循序讀取 cap，播放時不用每幀 seek
        self._play_seq_cap = None
        self._play_seq_idx = start_frame
        if self.renderer.video_path:
            safe = get_safe_path(self.renderer.video_path)
            _cap = cv2.VideoCapture(safe)
            if _cap.isOpened():
                _cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start_frame - 1))
                self._play_seq_cap = _cap

        self.start_preview_audio()
        # +0.12s 補償 ffplay 啟動延遲，讓畫面等聲音就緒後再推進
        self._preview_play_start_time = time.perf_counter() + 0.12
        self._last_playback_ui_sync_time = 0.0
        self._play_preview_step()

    def stop_preview_playback(self):
        self.preview_playing = False
        if self._preview_play_after_id is not None:
            try:
                self.after_cancel(self._preview_play_after_id)
            except Exception:
                pass
            self._preview_play_after_id = None
        _cap = getattr(self, "_play_seq_cap", None)
        if _cap is not None:
            _cap.release()
            self._play_seq_cap = None
        self.stop_audio_preview()

    def _play_preview_step(self):
        if not self.preview_playing:
            return
        fps   = max(self.renderer.fps or 30, 1)
        total = max(1, int(self.renderer.total_frames or self._preview_play_start_frame))
        elapsed      = max(0.0, time.perf_counter() - self._preview_play_start_time)
        target_frame = min(total, self._preview_play_start_frame + int(elapsed * fps))

        cap = getattr(self, "_play_seq_cap", None)

        # 播放剪後：遇到剪掉段落跳過，循序 cap 也一起 seek 到跳轉點
        if getattr(self, "_play_edited", False) and self.renderer.cut_ranges:
            current_secs = (target_frame - 1) / fps
            for s, e in self.renderer.cut_ranges:
                if s <= current_secs < e:
                    jump = max(1, min(total, int(e * fps) + 1))
                    if cap is not None:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, jump - 1))
                        self._play_seq_idx = jump
                    self._preview_play_start_frame = jump
                    self._preview_play_start_time  = time.perf_counter() + 0.12
                    self.slider_timeline.set(jump)
                    self.stop_audio_preview()
                    self.start_preview_audio()
                    target_frame = jump
                    break

        # 循序讀幀追上 target_frame：落後時跳幀，超前時什麼都不做
        cv_frame     = None
        actual_frame = max(1, self._play_seq_idx - 1)

        if cap is not None and cap.isOpened():
            while self._play_seq_idx <= target_frame:
                ret, f = cap.read()
                if not ret:
                    self.stop_preview_playback()
                    return
                cv_frame     = f
                actual_frame = self._play_seq_idx
                self._play_seq_idx += 1

        if actual_frame >= total:
            self.stop_preview_playback()
            return

        now = time.perf_counter()
        self.slider_timeline.set(actual_frame)
        sync_ui = now - getattr(self, "_last_playback_ui_sync_time", 0.0) >= 0.20
        self.update_timecode_and_waveform(actual_frame, draw_waveform=sync_ui)
        if sync_ui:
            self._last_playback_ui_sync_time = now
            self.sync_fields_for_frame(actual_frame)

        # 已解碼幀直接套泡泡，完全不需再 seek
        if cv_frame is not None and not self._preview_render_pending:
            self._last_preview_render_time = now
            self._render_play_frame(cv_frame, actual_frame)

        delay_ms = max(8, int(1000 / min(fps, 60)))
        self._preview_play_after_id = self.after(delay_ms, self._play_preview_step)

    def _render_play_frame(self, cv_frame, frame_idx):
        """播放專用渲染：直接對已解碼幀套泡泡，不再 seek VideoCapture。"""
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
            return True
        except Exception:
            self._ffplay_process = None
            return False

    # ------------------------------------------------------------------ 音訊
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
        source_path = getattr(self.renderer, "source_video_path", None) or self.renderer.video_path
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
        proc = self._ffplay_process
        self._ffplay_process = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------ 日誌
    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.status_label.configure(text=text)

    def toggle_log_panel(self):
        if self._log_expanded:
            self.log_box.grid_forget()
            self.btn_toggle_log.configure(text="顯示記錄")
            self._log_expanded = False
        else:
            self.log_box.grid(row=12, column=0, sticky="nsew", padx=12, pady=(4, 12))
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
                        self.progress_bar.set(msg["value"])
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
        except Exception:
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
            if self.slider_timeline.cget("state") == "normal":
                self.refresh_current_preview()

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

    def _toggle_person_boxes(self):
        self._show_person_boxes = not getattr(self, "_show_person_boxes", True)
        if hasattr(self, "btn_toggle_boxes"):
            self.btn_toggle_boxes.configure(
                text="顯示人物框" if not self._show_person_boxes else "隱藏人物框"
            )
        self._refresh_canvas()

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

        cut_secs = sum(max(0.0, e - s) for s, e in (self.renderer.cut_ranges or []))
        edited_secs = max(0.0, total_secs - cut_secs)

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
        self.entry_id.delete(0, "end")
        self.entry_id.insert(0, str(matched_tid))
        self.entry_speaker.delete(0, "end")
        self.entry_speaker.insert(0, row_speaker or speaker)
        self.entry_text.delete(0, "end")
        self.entry_text.insert(0, row_text or text)
        self._loading_person_fields = False
        if previous_row != self.selected_dialogue_row:
            self.update_script_selection_styles()

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
        self._clear_waveform_audio_cache()
        self._cleanup_proxy_video()
        self.destroy()
