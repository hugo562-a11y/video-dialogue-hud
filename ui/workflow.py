"""Workflow mixin for video loading, speech recognition, scanning, and export."""
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
from tkinter import filedialog, messagebox, simpledialog

from core.constants import (
    APP_TITLE, MIN_SILENCE_SECONDS, SILENCE_SPEAKER, SILENCE_TEXT,
    get_safe_path,
)
from core.data_processor import DataProcessor
from core.video_renderer import BUBBLE_COLOR_OPTIONS, BUBBLE_POSITION_OPTIONS, BUBBLE_STYLE_OPTIONS
from core.utils import (
    available_output_path,
    format_time_range,
    format_timecode,
    parse_time_range,
    seconds_to_frame,
)


class WorkflowMixin:

    def set_workflow_stage(self, stage: str, message: str = ""):
        labels = getattr(self, "workflow_group_labels", {})
        order = ["import", "speech", "people", "export"]
        active_index = order.index(stage) if stage in order else -1
        for index, key in enumerate(order):
            label = labels.get(key)
            if not label:
                continue
            if index < active_index:
                color = "#43E2A8"
            elif index == active_index:
                color = "#FBBF24"
            else:
                color = "#AAB0C0"
            label.configure(text_color=color)
        if message and hasattr(self, "status_label"):
            self.status_label.configure(text=message)

    # ------------------------------------------------------------------ 影片
    def select_video(self):
        self.stop_preview_playback()
        path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv")])
        if not path:
            return
        self.renderer.source_video_path = path
        self.renderer.video_path = None
        self.renderer.data_processor = DataProcessor()
        self.renderer.tracking_data = {}
        self.renderer.set_cut_ranges([])
        self.renderer.person_rois = []
        self.renderer.yolo_id_to_speaker = {}
        self.renderer.expected_people_count = 1
        self._speech_segments = None
        self._speech_audio_path = None
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
        if hasattr(self, "btn_export"):
            self.btn_export.configure(state="disabled")
        if hasattr(self, "btn_export_preview"):
            self.btn_export_preview.configure(state="disabled")
        if hasattr(self, "btn_open_export"):
            self._last_export_path = ""
            self.btn_open_export.configure(state="disabled", text="開啟輸出影片")
        if hasattr(self, "btn_scan"):
            self.btn_scan.configure(state="disabled")
        if hasattr(self, "btn_speech"):
            self.btn_speech.configure(state="disabled")
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="disabled")
        if hasattr(self, "btn_load_data"):
            self.btn_load_data.configure(state="disabled")
        if hasattr(self, "btn_save_data"):
            self.btn_save_data.configure(state="disabled")
        if hasattr(self, "whisper_menu"):
            self.whisper_menu.configure(state="disabled")
        self.btn_draw_people.configure(state="disabled")
        self.btn_confirm_people.configure(state="disabled")
        self.btn_clear_people.configure(state="disabled")
        self.progress_bar.set(0)
        self.set_workflow_stage("import", "正在建立或載入 720 proxy。")
        self.set_workflow_stage("import", "正在建立或載入 720 proxy。")
        self._proxy_source_pending = path
        self._cleanup_proxy_video()
        self.log(f"已選擇影片：{os.path.basename(path)}")
        self.log("正在建立或載入 720 proxy，讓預覽與時間軸更順。")
        threading.Thread(target=self._prepare_proxy_video, args=(path,), daemon=True).start()
        return
    def _prepare_proxy_video(self, source_path: str):
        try:
            proxy_path = self._build_proxy_video(source_path)
            self.ui_queue.put({"type": "proxy_done", "source_path": source_path, "proxy_path": proxy_path})
        except Exception as exc:
            self.ui_queue.put({"type": "error", "text": f"Proxy video creation failed: {exc}"})

    def _build_proxy_video(self, source_path: str) -> str:
        proxy_path = self._proxy_path_for_source(source_path)
        if self._is_proxy_current(source_path, proxy_path):
            self.ui_queue.put({"type": "error_log", "text": f"Using existing proxy: {os.path.basename(proxy_path)}"})
            return proxy_path

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg was not found.")
        safe_source = get_safe_path(source_path)
        temp_proxy_path = proxy_path + ".tmp.mp4"
        # Normalize non-square pixels first, then create a square-pixel working file.
        # Landscape is capped at 1280x720; portrait is capped at 720x1280.
        vf = (
            "scale='trunc(iw*sar/2)*2':ih,"
            "setsar=1,"
            "scale='if(gte(iw,ih),min(1280,iw),min(720,iw))':-2,"
            "setsar=1"
        )
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-i", safe_source,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            temp_proxy_path,
        ]
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        if result.returncode != 0 or not os.path.exists(temp_proxy_path):
            try:
                if os.path.exists(temp_proxy_path):
                    os.remove(temp_proxy_path)
            except OSError:
                pass
            detail = result.stderr.decode("utf-8", errors="ignore").strip().splitlines()
            raise RuntimeError(detail[-1] if detail else "ffmpeg returned no output.")
        os.replace(temp_proxy_path, proxy_path)
        return proxy_path

    def _proxy_path_for_source(self, source_path: str) -> str:
        root, _ext = os.path.splitext(source_path)
        return root + "_hud_proxy.mp4"

    def _is_proxy_current(self, source_path: str, proxy_path: str) -> bool:
        if not os.path.exists(proxy_path):
            return False
        try:
            if os.path.getmtime(proxy_path) < os.path.getmtime(source_path):
                return False
            cap = cv2.VideoCapture(get_safe_path(proxy_path))
            ok = cap.isOpened()
            if ok:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                ok = frames > 0 and max(width, height) <= 1280 and min(width, height) <= 720
            cap.release()
            return ok
        except OSError:
            return False

    def on_proxy_done(self, source_path: str, proxy_path: str):
        if getattr(self, "_proxy_source_pending", None) != source_path:
            return
        self._proxy_source_pending = None
        self._proxy_video_path = proxy_path
        self.renderer.source_video_path = source_path
        self.renderer.video_path = proxy_path

        safe_path = get_safe_path(proxy_path)
        cap = cv2.VideoCapture(safe_path)
        if not cap.isOpened():
            messagebox.showerror(APP_TITLE, "Proxy 影片無法開啟。")
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
        self.set_workflow_stage("speech", "代理檔完成，正在辨識聲音並產生腳本。")
        self.log(f"Proxy 完成：{width}x{height}，{total_frames} frames")
        threading.Thread(target=self._generate_waveform, daemon=True).start()
        self.generate_speech_script()

    def _cleanup_proxy_video(self):
        self._proxy_video_path = None

    # ------------------------------------------------------------------ Person boxes
    def start_person_box_mode(self):
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        self._canvas_mode = "person_roi"
        self.btn_draw_people.configure(text="框選中...", fg_color="#B94A48")
        self.log("請在預覽畫面框選人物。")
    def confirm_people_count(self):
        if not self.renderer.person_rois:
            messagebox.showinfo(APP_TITLE, "請先框選人物。")
            return
        self.renderer.expected_people_count = len(self.renderer.person_rois)
        for idx in range(1, self.renderer.expected_people_count + 1):
            self.renderer.yolo_id_to_speaker.setdefault(idx, f"人物 {idx}")
        self._update_box_and_scan_state()
        self.log(f"已確認 {self.renderer.expected_people_count} 個人物框。")

    def _update_box_and_scan_state(self):
        self.renderer.expected_people_count = max(1, len(self.renderer.person_rois))
        if hasattr(self, "btn_scan"):
            self.btn_scan.configure(
                state="normal" if self.renderer.person_rois and self.renderer.data_processor.has_data() else "disabled"
            )
        if hasattr(self, "btn_clear_people"):
            self.btn_clear_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_confirm_people"):
            self.btn_confirm_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="normal")
        self.renderer.tracking_data = {}
        self.renderer.yolo_id_to_speaker = dict(self.renderer.yolo_id_to_speaker)

    def mark_people_count_unconfirmed(self):
        if not self.renderer.video_path:
            return
        self.renderer.expected_people_count = max(1, len(self.renderer.person_rois))
        if hasattr(self, "btn_scan"):
            self.btn_scan.configure(
                state="normal" if self.renderer.person_rois and self.renderer.data_processor.has_data() else "disabled"
            )
        if hasattr(self, "btn_export"):
            self.btn_export.configure(state="disabled")
        if hasattr(self, "btn_confirm_people"):
            self.btn_confirm_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="normal")
        self.renderer.tracking_data = {}
        self.log("人物框已變更，請重新確認或掃描。")

    def clear_person_boxes(self):
        self.renderer.person_rois = []
        self.preview_boxes = []
        self.renderer.expected_people_count = 1
        self.renderer.tracking_data = {}
        self.btn_clear_people.configure(state="disabled")
        self.btn_speech.configure(state="normal")
        self.whisper_menu.configure(state="normal")
        self.btn_load_data.configure(state="normal" if self.renderer.data_processor.has_data() else "disabled")
        self.btn_scan.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self._refresh_canvas()
        self.log("已清除人物框。")

    def use_current_boxes_as_rois(self):
        if not self.preview_boxes:
            messagebox.showinfo(APP_TITLE, "目前畫面沒有可用人物框。")
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
        self.log(f"已用目前畫面更新 {len(rois)} 個人物框。")

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
                message += f"，已加入 {added} 段無講話"
        self.log(message)
        if success:
            self.btn_scan.configure(state="normal" if self.renderer.person_rois else "disabled")
            self.btn_save_data.configure(state="normal")
            self.refresh_script_panel()
            speakers = self.renderer.data_processor.get_unique_speakers()
            if speakers:
                self.entry_speaker.delete(0, "end")
                self.entry_speaker.insert(0, speakers[0])
                self.log(f"偵測到說話者：{', '.join(speakers[:8])}")
            # Enable timeline preview once script data is available.
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
        video_base_path = getattr(self.renderer, "source_video_path", None) or self.renderer.video_path
        if video_base_path:
            base = os.path.splitext(video_base_path)[0]
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
            out_df = dp.export_dataframe()
            if ext == ".xlsx":
                out_df.to_excel(path, index=False)
            else:
                out_df.to_csv(path, index=False, encoding="utf-8-sig")
            dp.path = path
            self.log(f"腳本已儲存：{os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"儲存失敗：{exc}")

    # ------------------------------------------------------------------ 基本資訊
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
        self.renderer.expected_people_count = max(1, len(self.renderer.person_rois))
        if self.renderer.expected_people_count == 1 and 1 not in self.renderer.yolo_id_to_speaker:
            self.renderer.yolo_id_to_speaker[1] = "人物 1"
        self.btn_speech.configure(state="disabled", text="辨識中...")
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="disabled")
        if hasattr(self, "btn_load_data"):
            self.btn_load_data.configure(state="disabled")
        self.whisper_menu.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始辨識聲音。")
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

            audio_source_path = getattr(self.renderer, "source_video_path", None) or self.renderer.video_path
            safe_path = get_safe_path(audio_source_path)
            model_size = self.whisper_model_var.get()
            self.ui_queue.put({"type": "progress", "value": 0.05})
            try:
                # Keep the Whisper model cached so repeated recognition does not reload it.
                cached = getattr(self, "_whisper_model", None)
                cached_size = getattr(self, "_whisper_model_size", None)
                if cached is None or cached_size != model_size:
                    self._whisper_model = WhisperModel(model_size, device="auto", compute_type="int8")
                    self._whisper_model_size = model_size
                model = self._whisper_model
                segments, _info = model.transcribe(
                    safe_path,
                    beam_size=5,
                    language="zh",
                    vad_filter=True,
                    word_timestamps=True,
                    vad_parameters={"min_silence_duration_ms": int(self.get_silence_seconds() * 1000)},
                    condition_on_previous_text=False,
                )
                self._speech_segments = list(segments)
                self._speech_audio_path = safe_path
                rows = self._segments_to_rows(
                    self._speech_segments,
                    self.renderer.total_frames,
                    self.renderer.fps,
                    self.get_silence_seconds(),
                    self._speech_audio_path,
                    model,
                )
            except RuntimeError as exc:
                if "cublas" not in str(exc).lower() and "cuda" not in str(exc).lower():
                    raise
                self.ui_queue.put({"type": "progress", "value": 0.1})
                self.ui_queue.put({"type": "error_log", "text": "CUDA 執行失敗，已改用 CPU。"})
                self._whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                self._whisper_model_size = model_size
                model = self._whisper_model
                segments, _info = model.transcribe(
                    safe_path,
                    beam_size=5,
                    language="zh",
                    vad_filter=True,
                    word_timestamps=True,
                    vad_parameters={"min_silence_duration_ms": int(self.get_silence_seconds() * 1000)},
                    condition_on_previous_text=False,
                )
                self._speech_segments = list(segments)
                self._speech_audio_path = safe_path
                rows = self._segments_to_rows(
                    self._speech_segments,
                    self.renderer.total_frames,
                    self.renderer.fps,
                    self.get_silence_seconds(),
                    self._speech_audio_path,
                    model,
                )

            if not rows:
                self.ui_queue.put({"type": "error", "text": "語音辨識沒有產生可用腳本。"})
                return

            video_base_path = getattr(self.renderer, "source_video_path", None) or self.renderer.video_path
            base = os.path.splitext(video_base_path)[0]
            out_csv = available_output_path(base + "_dialogue.csv")
            pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8-sig")
            self.ui_queue.put({"type": "speech_done", "rows": rows, "out_csv": out_csv})
        except ModuleNotFoundError as exc:
            if exc.name == "faster_whisper":
                self.ui_queue.put({"type": "error", "text": "缺少 faster-whisper，請先安裝。"})
            else:
                self.ui_queue.put({"type": "error", "text": f"缺少套件：{exc.name}"})
        except Exception as exc:
            self.ui_queue.put({"type": "error", "text": f"語音辨識失敗：{exc}"})

    def on_speech_done(self, rows, out_csv):
        if hasattr(self, "btn_speech"):
            self.btn_speech.configure(state="normal", text="2  重新辨識聲音")
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="normal")
        if hasattr(self, "btn_load_data"):
            self.btn_load_data.configure(state="normal")
        if hasattr(self, "whisper_menu"):
            self.whisper_menu.configure(state="normal")
        if hasattr(self, "btn_draw_people"):
            self.btn_draw_people.configure(state="normal")
        if hasattr(self, "btn_confirm_people"):
            self.btn_confirm_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_clear_people"):
            self.btn_clear_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_scan"):
            self.btn_scan.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="normal")
        if hasattr(self, "btn_save_data"):
            self.btn_save_data.configure(state="normal")
        self.progress_bar.set(1)
        self.set_workflow_stage("people", "腳本已建立。先修正時間，再命名人物並框選。")
        self.btn_speech.configure(text="重新辨識聲音")
        self.btn_scan.configure(text="掃描人物")
        self.btn_export.configure(text="匯出完成品")
        silence_count = sum(1 for row in rows if row.get("說話者") == SILENCE_SPEAKER)
        df = pd.DataFrame(rows)
        self.renderer.data_processor.set_dataframe(df, os.path.basename(out_csv))
        self.selected_dialogue_row = 0 if len(df) else None
        self.refresh_script_panel()
        self.log(f"語音腳本已建立：{os.path.basename(out_csv)}，無講話 {silence_count} 段")
        self.log("接著會進行聲紋辨識並開啟人物命名。")
        ids = list(range(1, max(1, self.renderer.expected_people_count) + 1))
        self.open_speaker_mapper(ids)
            # Enable timeline preview once script data is available.
        if self.renderer.total_frames:
            self.slider_timeline.configure(state="normal", from_=1, to=self.renderer.total_frames)
            self.slider_timeline.set(1)
            self.on_timeline_scrub(1)

    def on_worker_error(self, text):
        if hasattr(self, "btn_speech"):
            self.btn_speech.configure(state="normal", text="2  辨識聲音")
        if hasattr(self, "btn_load_data"):
            self.btn_load_data.configure(state="normal")
        if hasattr(self, "whisper_menu"):
            self.whisper_menu.configure(state="normal")
        if hasattr(self, "btn_draw_people"):
            self.btn_draw_people.configure(state="normal")
        if hasattr(self, "btn_confirm_people"):
            self.btn_confirm_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        if hasattr(self, "btn_clear_people"):
            self.btn_clear_people.configure(state="normal" if self.renderer.person_rois else "disabled")
        self.btn_scan.configure(
            state="normal" if self.renderer.data_processor.has_data() and self.renderer.person_rois else "disabled",
            text="5  掃描人物",
        )
        if hasattr(self, "btn_name_people"):
            self.btn_name_people.configure(state="normal" if self.renderer.data_processor.has_data() else "disabled")
        self.btn_export.configure(
            state="normal" if self.renderer.tracking_data else "disabled",
            text="6  匯出完成品",
        )
        self.log(text)
        messagebox.showerror(APP_TITLE, text)

    # ------------------------------------------------------------------ 掃描
    def start_preview_scan(self):
        self.set_workflow_stage("people", "正在掃描人物，請稍候。")
        self.stop_preview_playback()
        if not self.renderer.video_path:
            messagebox.showinfo(APP_TITLE, "請先選擇影片。")
            return
        if not self.renderer.person_rois:
            messagebox.showinfo(APP_TITLE, "請先框選人物。")
            return
        if not self.renderer.data_processor.has_data():
            messagebox.showinfo(APP_TITLE, "請先建立或載入腳本。")
            return
        self.renderer.expected_people_count = len(self.renderer.person_rois)
        self.btn_scan.configure(state="disabled", text="掃描中...")
        if hasattr(self, "btn_export_preview"):
            self.btn_export_preview.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self.slider_timeline.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始掃描人物。")
        threading.Thread(target=self.renderer.scan_video, daemon=True).start()

    def on_scan_finished(self):
        self.btn_scan.configure(state="normal", text="5  重新掃描人物")
        if self.renderer.tracking_data:
            self.slider_timeline.configure(state="normal", from_=1, to=max(1, self.renderer.total_frames))
            self.slider_timeline.set(1)
            if hasattr(self, "btn_export_preview"):
                self.btn_export_preview.configure(state="normal")
            self.btn_export.configure(state="normal")
            self.set_workflow_stage("export", "人物掃描完成。抽查字幕與泡泡位置，確認後匯出。")
            self.btn_scan.configure(text="重新掃描人物")
            self.btn_export.configure(text="匯出完成品")
            first_frame = next((idx for idx, boxes in self.renderer.tracking_data.items() if boxes), 1)
            self.slider_timeline.set(first_frame)
            self.on_timeline_scrub(first_frame)
            ids = sorted({box["id"] for boxes in self.renderer.tracking_data.values() for box in boxes})
            self.log(f"掃描完成，偵測 ID：{', '.join(map(str, ids)) if ids else '無'}")
        else:
            self.log("掃描完成，但沒有偵測到人物。")

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

    def _delete_preview_export(self):
        path = getattr(self, "_last_preview_export_path", "")
        if path and os.path.exists(path):
            try:
                os.remove(path)
                self.log(f"已刪除預覽影片：{path}")
            except OSError as exc:
                self.log(f"預覽影片刪除失敗：{exc}")
        self._last_preview_export_path = ""

    def start_preview_export(self):
        self.set_workflow_stage("export", "正在匯出 720 proxy 預覽影片。")
        self.stop_preview_playback()
        if not self.renderer.tracking_data:
            messagebox.showinfo(APP_TITLE, "請先掃描人物。")
            return
        self._sync_selected_person_fields()
        self.renderer.set_cut_ranges(
            self.renderer.data_processor.get_export_cut_ranges(self.get_video_duration())
        )
        self.stop_audio_preview()
        self._exporting_preview = True
        self.btn_export_preview.configure(state="disabled", text="預覽匯出中...")
        self.btn_export.configure(state="disabled")
        self.btn_scan.configure(state="disabled")
        self.slider_timeline.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始匯出預覽影片。")
        threading.Thread(target=lambda: self.renderer.export_video(preview=True), daemon=True).start()

    def start_export(self):
        self.set_workflow_stage("export", "正在以原始影片尺寸匯出完成品。")
        self.stop_preview_playback()
        if not self.renderer.tracking_data:
            messagebox.showinfo(APP_TITLE, "請先掃描人物。")
            return
        self._delete_preview_export()
        self._sync_selected_person_fields()
        self.renderer.set_cut_ranges(
            self.renderer.data_processor.get_export_cut_ranges(self.get_video_duration())
        )
        self.stop_audio_preview()
        self._exporting_preview = False
        if hasattr(self, "btn_export_preview"):
            self.btn_export_preview.configure(state="disabled")
        self.btn_export.configure(state="disabled", text="匯出中...")
        self.btn_scan.configure(state="disabled")
        self.slider_timeline.configure(state="disabled")
        self.progress_bar.set(0)
        self.log("開始匯出完成品。")
        threading.Thread(target=lambda: self.renderer.export_video(preview=False), daemon=True).start()

    def on_export_finished(self, out_path):
        is_preview = bool(getattr(self, "_exporting_preview", False))
        self._exporting_preview = False
        if is_preview:
            self.set_workflow_stage("export", "預覽匯出完成，可檢查後再匯出完成品。")
        else:
            self.set_workflow_stage("export", "匯出完成。可開啟輸出影片檢查結果。")
        if hasattr(self, "btn_export_preview"):
            self.btn_export_preview.configure(state="normal", text="重新匯出預覽")
        self.btn_export.configure(state="normal", text="重新匯出完成品")
        self.btn_scan.configure(state="normal", text="重新掃描人物")
        self.slider_timeline.configure(state="normal")
        self.progress_bar.set(1)
        if out_path:
            if is_preview:
                self._last_preview_export_path = out_path
            self._last_export_path = out_path
            if hasattr(self, "btn_open_export"):
                self.btn_open_export.configure(state="normal", text="開啟輸出影片")
            self.log(f"匯出完成：{out_path}")
        else:
            self.log("匯出失敗。")

    def open_export_video(self):
        path = getattr(self, "_last_export_path", "")
        if not path or not os.path.exists(path):
            messagebox.showinfo(APP_TITLE, "找不到可開啟的影片。")
            return
        try:
            os.startfile(path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"開啟影片失敗：{exc}")

    # ------------------------------------------------------------------ 人物命名
    def open_speaker_mapper(self, ids):
        ids = list(ids) if ids else [1]
        win = ctk.CTkToplevel(self)
        win.title("命名人物")
        win.geometry("720x500")
        win.transient(self)
        win.grab_set()
        header_frame = ctk.CTkFrame(win, fg_color="transparent")
        header_frame.pack(fill="x", pady=(16, 8), padx=14)
        self._speaker_mapper_info = ctk.CTkLabel(
            header_frame,
            text="確認人物名稱、泡泡顏色、樣式與位置。",
            font=("Microsoft JhengHei UI", 16, "bold"),
            anchor="w",
        )
        self._speaker_mapper_info.pack(side="left", fill="x", expand=True)
        add_person_button = ctk.CTkButton(
            header_frame,
            text="新增人物",
            width=120,
            command=lambda: add_person(),
        )
        add_person_button.pack(side="right")

        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(expand=True, fill="both", padx=14, pady=8)
        rows = []
        color_names = list(BUBBLE_COLOR_OPTIONS.keys())

        def make_row(tid):
            row = ctk.CTkFrame(scroll)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"人物 {tid}", width=70, font=("Arial", 13, "bold")).pack(side="left", padx=8, pady=8)
            value = self.renderer.yolo_id_to_speaker.get(tid, f"人物 {tid}")
            entry = ctk.CTkEntry(row, width=160)
            entry.insert(0, value)
            entry.pack(side="left", padx=6)
            style = self.renderer.get_person_bubble_style(tid)
            color_var = ctk.StringVar(value=style["color"])
            style_var = ctk.StringVar(value=style["style"])
            position_var = ctk.StringVar(value=style["position"])
            swatch = ctk.CTkLabel(
                row, text="", width=24, height=24,
                fg_color=self._bubble_color_hex(color_var.get()),
                corner_radius=6,
            )
            swatch.pack(side="left", padx=(10, 4))
            ctk.CTkOptionMenu(
                row,
                values=color_names,
                variable=color_var,
                width=72,
                command=lambda val, label=swatch: label.configure(fg_color=self._bubble_color_hex(val)),
            ).pack(side="left", padx=4)
            ctk.CTkOptionMenu(
                row,
                values=BUBBLE_STYLE_OPTIONS,
                variable=style_var,
                width=104,
            ).pack(side="left", padx=4)
            ctk.CTkOptionMenu(
                row,
                values=BUBBLE_POSITION_OPTIONS,
                variable=position_var,
                width=84,
            ).pack(side="left", padx=4)
            rows.append((tid, entry, color_var, style_var, position_var))

        def add_person():
            next_tid = max([item[0] for item in rows], default=0) + 1
            make_row(next_tid)
            self._speaker_mapper_info.configure(
                text="已新增人物，請設定名稱與樣式。"
            )

        for tid in ids:
            make_row(tid)

        def save():
            self.push_undo_state("更新人物名稱")
            self.renderer.expected_people_count = max(len(rows), 1)
            old_speakers = {
                tid: self.renderer.yolo_id_to_speaker.get(tid, f"人物 {tid}")
                for tid, _, _, _, _ in rows
            }
            for tid, entry, color_var, style_var, position_var in rows:
                speaker = entry.get().strip()
                if speaker:
                    self.renderer.yolo_id_to_speaker[tid] = speaker
                self.renderer.set_person_bubble_style(tid, style_var.get(), color_var.get(), position_var.get())
            for idx in range(1, self.renderer.expected_people_count + 1):
                self.renderer.yolo_id_to_speaker.setdefault(idx, f"人物 {idx}")
            self.renderer.bubble_cache.clear()
            if getattr(self, "_speech_segments", None):
                self.reassign_speech_rows()
                self.log(f"已依 {self.renderer.expected_people_count} 個人物重新分配聲紋。")
            else:
                renamed = 0
                for tid, entry, _, _, _ in rows:
                    old_speaker = old_speakers.get(tid, f"人物 {tid}")
                    speaker = entry.get().strip()
                    if speaker:
                        renamed += self.renderer.data_processor.replace_speaker(old_speaker, speaker)
                self.log(f"已更新腳本中的 {renamed} 筆說話者。")
            self.on_timeline_scrub(self.slider_timeline.get())
            self.refresh_script_panel()
            win.destroy()

        ctk.CTkButton(win, text="套用", command=save, height=36).pack(pady=(6, 16))

    def _prompt_person_count(self):
        if self.renderer.person_rois or self.renderer.expected_people_count != 1:
            return
        count = simpledialog.askinteger(
            APP_TITLE,
            "請輸入人物數量。",
            parent=self,
            minvalue=1,
            maxvalue=12,
            initialvalue=2,
        )
        if count is None:
            return
        self.renderer.expected_people_count = max(1, count)
        for idx in range(1, self.renderer.expected_people_count + 1):
            self.renderer.yolo_id_to_speaker.setdefault(idx, f"人物 {idx}")
        if getattr(self, "_speech_segments", None):
            self.reassign_speech_rows()

    def open_person_namer(self):
        ids = list(range(1, max(1, self.renderer.expected_people_count) + 1))
        self.open_speaker_mapper(ids)

    def reassign_speech_rows(self):
        if not getattr(self, "_speech_segments", None):
            return False
        model = getattr(self, "_whisper_model", None)
        if model is None:
            try:
                from faster_whisper import WhisperModel
                model_size = self.whisper_model_var.get()
                self._whisper_model = WhisperModel(model_size, device="auto", compute_type="int8")
                self._whisper_model_size = model_size
                model = self._whisper_model
            except Exception:
                model = None
        audio_path = getattr(self, "_speech_audio_path", self.renderer.video_path)
        rows = self._segments_to_rows(
            self._speech_segments,
            self.renderer.total_frames,
            self.renderer.fps,
            self.get_silence_seconds(),
            audio_path,
            model,
        )
        if not rows:
            return False
        self.renderer.data_processor.set_dataframe(pd.DataFrame(rows), self.renderer.data_processor.path or "辨識腳本")
        self.selected_dialogue_row = 0 if len(rows) else None
        self.refresh_script_panel()
        return True

    def _set_entry(self, entry, value):
        entry.delete(0, "end")
        entry.insert(0, value)

    def _bubble_color_hex(self, color_name: str) -> str:
        rgba, _ = BUBBLE_COLOR_OPTIONS.get(color_name, next(iter(BUBBLE_COLOR_OPTIONS.values())))
        return "#{:02X}{:02X}{:02X}".format(rgba[0], rgba[1], rgba[2])

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

    def _assign_speakers_resemblyzer(self, entries, audio, audio_rate, n_speakers):
        """Assign each speech entry to a speaker cluster with resemblyzer embeddings."""
        if n_speakers <= 1 or not entries or audio is None:
            return [0] * len(entries)
        try:
            from resemblyzer import VoiceEncoder, preprocess_wav
            from sklearn.cluster import KMeans

            if not getattr(self, "_voice_encoder", None):
                self._voice_encoder = VoiceEncoder()
            encoder = self._voice_encoder

            embeddings = []
            # 最短 0.5 秒，太短的片段聲紋不穩定，用零向量佔位
            min_samples = int(audio_rate * 0.5)
            for entry in entries:
                s = int(entry["start"] * audio_rate)
                e = int(entry["end"] * audio_rate)
                chunk = audio[s:e]
                if chunk.size < min_samples:
                    embeddings.append(np.zeros(256, dtype=np.float32))
                else:
                    wav = preprocess_wav(chunk.astype(np.float32), source_sr=int(audio_rate))
                    emb = encoder.embed_utterance(wav)
                    embeddings.append(emb)

            emb_array = np.array(embeddings, dtype=np.float32)
            if not np.any(emb_array):
                return [0] * len(entries)

            # L2 正規化：讓 K-Means 使用 Euclidean 距離等效於餘弦相似度
            norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            emb_array = emb_array / norms

            k = min(n_speakers, len(entries))
            labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(emb_array)
            return labels.tolist()
        except Exception:
            return [0] * len(entries)

    def _estimate_speaker_count_resemblyzer(self, entries, audio, audio_rate, max_speakers: int = 6) -> int:
        if len(entries) < 2 or audio is None or audio_rate <= 0:
            return 1
        try:
            from resemblyzer import VoiceEncoder, preprocess_wav
            from sklearn.cluster import AgglomerativeClustering

            if not getattr(self, "_voice_encoder", None):
                self._voice_encoder = VoiceEncoder()
            encoder = self._voice_encoder

            embeddings = []
            min_samples = int(audio_rate * 0.7)
            for entry in entries:
                s = int(max(0.0, entry["start"]) * audio_rate)
                e = int(max(entry["start"], entry["end"]) * audio_rate)
                chunk = audio[s:e]
                if chunk.size < min_samples:
                    continue
                wav = preprocess_wav(chunk.astype(np.float32), source_sr=int(audio_rate))
                emb = encoder.embed_utterance(wav)
                if np.any(emb):
                    embeddings.append(emb)

            if len(embeddings) < 2:
                return 1

            emb_array = np.array(embeddings, dtype=np.float32)
            norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            emb_array = emb_array / norms

            # 自動找閾值：固定值對人少時太鬆（2人→3群）、人多時太緊（6人→1群）。
            # 做法：取所有成對餘弦距離，找最大跳躍點（同人距離 vs 不同人距離之間的缺口），
            # 把閾值設在缺口中間，自動適應不同人數場景。
            from sklearn.metrics.pairwise import cosine_distances
            dist_mat = cosine_distances(emb_array)
            pairs = np.triu_indices(len(emb_array), k=1)
            all_dists = np.sort(dist_mat[pairs])

            if len(all_dists) >= 4:
                gaps = np.diff(all_dists)
                gap_pos = int(np.argmax(gaps))
                threshold = float(np.clip(
                    (all_dists[gap_pos] + all_dists[gap_pos + 1]) / 2,
                    0.22, 0.52,
                ))
            else:
                threshold = 0.35

            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=threshold,
                metric="cosine",
                linkage="average",
            )
            labels = clustering.fit_predict(emb_array)
            n_clusters = len(set(labels))
            return max(1, min(n_clusters, max_speakers))
        except Exception as exc:
            self.ui_queue.put({"type": "error_log", "text": f"聲紋估算失敗，先使用 1 個人物：{exc}"})
            return 1

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
            self.ui_queue.put({"type": "error_log", "text": f"補回 {recovered_count} 段可能漏辨語音。"})

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

        # ---- 聲紋估算人物數 ----
        n_speakers = max(1, getattr(self.renderer, "expected_people_count", 1) or 1)
        if not self.renderer.person_rois and n_speakers <= 1:
            self.ui_queue.put({"type": "error_log", "text": "語音辨識完成，正在進行聲紋估算人物數..."})
            estimated = self._estimate_speaker_count_resemblyzer(cleaned, audio, audio_rate)
            if estimated > 1:
                self.renderer.expected_people_count = estimated
                n_speakers = estimated
                for idx in range(1, estimated + 1):
                    self.renderer.yolo_id_to_speaker.setdefault(idx, f"人物 {idx}")
                self.ui_queue.put({"type": "error_log", "text": f"聲紋估算為 {estimated} 個人物。"})
            else:
                self.ui_queue.put({"type": "error_log", "text": "聲紋估算為 1 個人物。"})
        if n_speakers > 1:
            self.ui_queue.put({"type": "error_log", "text": f"正在依 {n_speakers} 個人物做聲紋分群。"})
        speaker_labels = self._assign_speakers_resemblyzer(cleaned, audio, audio_rate, n_speakers)
        if n_speakers > 1 and any(l != 0 for l in speaker_labels):
            self.ui_queue.put({"type": "error_log", "text": "聲紋分群完成。"})

        rows = []
        last_end = 0.0
        for index, (item, spk_idx) in enumerate(zip(cleaned, speaker_labels), start=1):
            if item["start"] - last_end >= min_silence:
                rows.append({
                    "時間": format_time_range(last_end, item["start"]),
                    "說話者": SILENCE_SPEAKER,
                    "對話": SILENCE_TEXT,
                })
            # spk_idx 是 0-based，yolo_id_to_speaker 是 1-based
            speaker_id = (spk_idx % n_speakers) + 1
            speaker_name = self.renderer.yolo_id_to_speaker.get(speaker_id, f"人物 {speaker_id}")
            rows.append({
                "時間": format_time_range(item["start"], item["end"]),
                "說話者": speaker_name,
                "對話": item["text"],
            })
            last_end = max(last_end, float(item["end"]))
            if index % 3 == 0:
                self.ui_queue.put({"type": "progress", "value": min(len(rows) / 80, 0.95)})

        video_end = total_frames / max(fps, 1) if total_frames and fps else None
        if video_end and video_end - last_end >= min_silence:
            rows.append({
                "時間": format_time_range(last_end, video_end),
                "說話者": SILENCE_SPEAKER,
                "對話": SILENCE_TEXT,
            })
        return rows
