"""WorkflowMixin — 影片選取、腳本載入/儲存、聲音辨識、掃描、匯出。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading

import cv2
import customtkinter as ctk
import numpy as np
import pandas as pd
from PIL import Image
from tkinter import filedialog, messagebox

from core.constants import (
    APP_TITLE, MIN_SILENCE_SECONDS, SILENCE_SPEAKER, SILENCE_TEXT,
    get_safe_path,
)
from core.data_processor import DataProcessor
from core.utils import (
    available_output_path,
    format_time_range,
    format_timecode,
    parse_time_range,
    seconds_to_frame,
)


class WorkflowMixin:

    # ------------------------------------------------------------------ 影片
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
        self.btn_save_data.configure(state="disabled")
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

    # ------------------------------------------------------------------ 人物框
    def start_person_box_mode(self):
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        self._canvas_mode = "person_roi"
        self.btn_draw_people.configure(text="拖曳框選中", fg_color="#B94A48")
        self.log("請在預覽畫面拖曳框住每一個要追蹤的人。每畫一框就是一個人。")

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
        self.log(f"已確認 {self.renderer.expected_people_count} 個人物框。請載入或辨識腳本，再掃描人物。")

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
        for box in sorted(self.preview_boxes, key=lambda b: b["id"]):
            x1, y1, x2, y2 = box["bbox"]
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            rois.append((
                max(0, int(x1 - w * 0.35)),
                max(0, int(y1 - h * 0.35)),
                int(x2 + w * 0.35),
                int(y2 + h * 2.2),
            ))
        self.renderer.person_rois = rois
        self.mark_people_count_unconfirmed()
        self.btn_clear_people.configure(state="normal")
        self._refresh_canvas()
        self.log(f"已用目前畫面更新 {len(rois)} 個人物框，請重新確認並掃描。")

    # ------------------------------------------------------------------ 腳本
    def load_data(self):
        path = filedialog.askopenfilename(filetypes=[("Dialogue Files", "*.csv *.xlsx *.xls")])
        if not path:
            return
        if self.renderer.data_processor.has_data():
            self.push_undo_state("載入腳本")
        success, message = self.renderer.data_processor.load_data(path)
        if success:
            added = self.renderer.data_processor.add_silence_rows(
                self.get_video_duration(), self.get_silence_seconds()
            )
            if added:
                message += f"，已補 {added} 段無講話"
        self.log(message)
        if success:
            self.btn_scan.configure(state="normal" if self.people_count_confirmed else "disabled")
            self.btn_save_data.configure(state="normal")
            self.refresh_script_panel()
            speakers = self.renderer.data_processor.get_unique_speakers()
            if speakers:
                self.entry_speaker.delete(0, "end")
                self.entry_speaker.insert(0, speakers[0])
                self.log(f"找到說話者：{', '.join(speakers[:8])}")
            # 開放滑桿，讓使用者拖動預覽字幕泡泡（掃描前字幕模式）
            if self.renderer.total_frames and not self.renderer.tracking_data:
                self.slider_timeline.configure(state="normal", from_=1, to=self.renderer.total_frames)
                self.slider_timeline.set(1)
                self.on_timeline_scrub(1)

    def save_data(self):
        dp = self.renderer.data_processor
        if not dp.has_data():
            messagebox.showinfo(APP_TITLE, "目前沒有腳本可儲存。")
            return
        default_name = ""
        if self.renderer.video_path:
            base = os.path.splitext(self.renderer.video_path)[0]
            default_name = available_output_path(base + "_dialogue.csv")
        elif dp.path and os.path.isfile(str(dp.path)):
            default_name = dp.path
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 檔案", "*.csv"), ("Excel 檔案", "*.xlsx")],
            initialfile=os.path.basename(default_name) if default_name else "dialogue.csv",
        )
        if not path:
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".xlsx":
                dp.df.to_excel(path, index=False)
            else:
                dp.df.to_csv(path, index=False, encoding="utf-8-sig")
            dp.path = path
            self.log(f"腳本已儲存：{os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"儲存失敗：{exc}")

    # ------------------------------------------------------------------ 工具
    def get_video_duration(self):
        if self.renderer.total_frames and self.renderer.fps:
            return self.renderer.total_frames / max(self.renderer.fps, 1)
        return None

    def get_silence_seconds(self):
        try:
            return max(0.2, float(self.silence_seconds_var.get()))
        except Exception:
            return MIN_SILENCE_SECONDS

    # ------------------------------------------------------------------ 語音辨識
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

    def on_speech_done(self, rows, out_csv):
        self.btn_speech.configure(state="normal", text="3  重新辨識聲音")
        self.btn_data.configure(state="normal")
        self.whisper_menu.configure(state="normal")
        self.btn_scan.configure(state="normal" if self.people_count_confirmed else "disabled")
        self.btn_save_data.configure(state="normal")
        self.progress_bar.set(1)
        silence_count = sum(1 for row in rows if row.get("說話者") == SILENCE_SPEAKER)
        df = pd.DataFrame(rows)
        self.renderer.data_processor.set_dataframe(df, os.path.basename(out_csv))
        self.selected_dialogue_row = 0 if len(df) else None
        self.refresh_script_panel()
        self.log(f"語音辨識完成，已產生腳本：{os.path.basename(out_csv)}，無講話 {silence_count} 段")
        # 腳本載入後開放滑桿，讓使用者拖動預覽字幕泡泡（掃描前字幕模式）
        if self.renderer.total_frames:
            self.slider_timeline.configure(state="normal", from_=1, to=self.renderer.total_frames)
            self.slider_timeline.set(1)
            self.on_timeline_scrub(1)

    def on_worker_error(self, text):
        self.btn_speech.configure(state="normal", text="3  辨識聲音產生腳本")
        self.btn_data.configure(state="normal")
        self.whisper_menu.configure(state="normal")
        self.btn_scan.configure(
            state="normal" if self.renderer.data_processor.has_data() else "disabled",
            text="4  掃描人物並對應",
        )
        self.btn_export.configure(
            state="normal" if self.renderer.tracking_data else "disabled",
            text="5  匯出影片",
        )
        self.log(text)
        messagebox.showerror(APP_TITLE, text)

    # ------------------------------------------------------------------ 掃描
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

    # ------------------------------------------------------------------ 匯出
    def _sync_selected_person_fields(self):
        try:
            tid = int(self.entry_id.get())
        except ValueError:
            return
        speaker = self.entry_speaker.get().strip()
        if speaker:
            self.renderer.yolo_id_to_speaker[tid] = speaker
        self.update_dialogue_text()

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

    # ------------------------------------------------------------------ 人物命名
    def open_speaker_mapper(self, ids):
        win = ctk.CTkToplevel(self)
        win.title("命名人物")
        win.geometry("520x420")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(
            win,
            text="先替每個人物框命名。腳本選單之後會出現這些名字。",
            font=("Microsoft JhengHei UI", 16, "bold"),
        ).pack(pady=(16, 8))
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
                ctk.CTkOptionMenu(
                    row,
                    values=suggestions,
                    variable=menu_var,
                    command=lambda val, ent=entry: self._set_entry(ent, val),
                ).pack(side="left", padx=6)
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

    # ------------------------------------------------------------------ 語音辨識輔助
    def _load_audio_for_timing(self, video_path, sample_rate=16000):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not video_path:
            return None, sample_rate
        cmd = [ffmpeg, "-v", "error", "-i", video_path, "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
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
            audio, sample_rate,
            max(min_left, start - 0.18),
            min(max_right, max(start + 0.24, min(end, start + 0.08))),
        )
        end_edges = self._local_active_edges(
            audio, sample_rate,
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
                audio, sample_rate, item["start"], item["end"],
                min_left=min_left, max_right=max_right,
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
            gaps.extend((u_s, u_e) for u_s, u_e in uncovered if u_e - u_s >= min_gap)
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
                temp_path, beam_size=5, language="zh", vad_filter=False,
                word_timestamps=True, no_speech_threshold=0.9, condition_on_previous_text=False,
            )
            recovered = []
            for segment in segments:
                text = str(segment.text).strip()
                if not text:
                    continue
                words = [w for w in getattr(segment, "words", None) or [] if getattr(w, "word", "").strip()]
                if words:
                    text = "".join(w.word.strip() for w in words).strip() or text
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
            words = [w for w in getattr(segment, "words", None) or [] if getattr(w, "word", "").strip()]
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
                text = "".join(w.word.strip() for w in item).strip()
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
            audio, audio_rate,
            min_active=0.10,
            bridge_gap=max(0.08, min(float(min_silence) * 0.45, 0.22)),
        )
        gaps = self._find_uncovered_activity_intervals(
            entries, activity_intervals,
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

        video_end = total_frames / max(fps, 1) if total_frames and fps else None
        if video_end and video_end - last_end >= min_silence:
            rows.append({
                "時間點": format_time_range(last_end, video_end),
                "說話者": SILENCE_SPEAKER,
                "對話內容": SILENCE_TEXT,
            })
        return rows
