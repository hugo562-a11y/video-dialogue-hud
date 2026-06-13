"""EditingMixin — 斷句、新增、刪除、合併、微調時間。"""
from __future__ import annotations

from tkinter import messagebox

from core.constants import APP_TITLE
from core.utils import (
    format_timecode,
    frame_to_seconds,
    parse_time_range,
)


class EditingMixin:

    def split_current_sentence(self):
        if self.selected_dialogue_row is None:
            messagebox.showinfo(APP_TITLE, "請先點選一個有對話的泡泡或人物框。")
            return
        text, cursor_pos = self.current_dialogue_text_and_cursor()
        if len(text.strip()) < 2:
            messagebox.showinfo(APP_TITLE, "這句太短，無法斷句。")
            return
        self.push_undo_state("切斷句")
        original_row_idx = self.selected_dialogue_row
        success, message, new_row_idx = self.renderer.data_processor.split_dialogue_row(
            self.selected_dialogue_row, cursor_pos, reset_index=False
        )
        self.log(message)
        if not success:
            messagebox.showinfo(APP_TITLE, message)
            return
        self.renderer.bubble_cache.clear()
        updated = False
        if hasattr(self, "update_script_row_from_data"):
            updated = self.update_script_row_from_data(original_row_idx)
        if hasattr(self, "insert_script_row_from_data"):
            updated = self.insert_script_row_from_data(new_row_idx, after_row_idx=original_row_idx) and updated
        if not updated:
            self.refresh_script_panel()
        if hasattr(self, "select_dialogue_row"):
            self.select_dialogue_row(new_row_idx, seek=False, scroll=False, redraw_waveform=False)
        else:
            self.selected_dialogue_row = new_row_idx
            self.update_current_sentence_label()
            self.refresh_script_action_buttons()
        if hasattr(self, "schedule_waveform_refresh"):
            self.schedule_waveform_refresh(delay_ms=160)
        if hasattr(self, "schedule_script_preview_refresh"):
            self.schedule_script_preview_refresh(delay_ms=350)

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

    def delete_selected_dialogue(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data() or row_idx not in dp.df.index:
            return "break"
        deleted = not dp.is_deleted(row_idx)
        self.push_undo_state("刪除句" if deleted else "還原句")
        if dp.set_deleted(row_idx, deleted):
            self.renderer.bubble_cache.clear()
            update_row = getattr(self, "update_script_row_deleted_state", None)
            if not update_row or not update_row(row_idx):
                self.refresh_script_panel()
            if hasattr(self, "draw_waveform") and hasattr(self, "current_frame"):
                self.draw_waveform(self.current_frame())
            if hasattr(self, "refresh_script_action_buttons"):
                self.refresh_script_action_buttons()
            self.refresh_current_preview()
            self.log("已標記刪除，匯出時會剪去該片段。" if deleted else "已還原這一句。")
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
            if hasattr(self, "update_script_row_from_data") and self.update_script_row_from_data(row_idx):
                self.draw_waveform(self.current_frame())
            else:
                self.refresh_script_panel()
            self.select_dialogue_row(row_idx, seek=False)
            self.refresh_current_preview()
        return "break"
