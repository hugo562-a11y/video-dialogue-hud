"""EditingMixin — 斷句、新增、刪除、合併、微調時間。"""
from __future__ import annotations

from tkinter import messagebox

from core.constants import APP_TITLE
from core.utils import (
    format_timecode,
    frame_to_seconds,
    normalize_time_ranges,
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
        success, message, new_row_idx = self.renderer.data_processor.split_dialogue_row(
            self.selected_dialogue_row, cursor_pos
        )
        self.log(message)
        if not success:
            messagebox.showinfo(APP_TITLE, message)
            return
        self.renderer.bubble_cache.clear()
        self.selected_dialogue_row = new_row_idx
        self.refresh_script_panel()
        if self.slider_timeline.cget("state") == "normal":
            self.refresh_current_preview()
        try:
            self.select_person(int(self.entry_id.get()))
        except Exception:
            pass

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
        self.push_undo_state("刪除句")
        if dp.delete_dialogue_row(row_idx):
            indices = self.dialogue_indices()
            self.selected_dialogue_row = indices[min(len(indices) - 1, max(0, row_idx))] if indices else None
            self.renderer.bubble_cache.clear()
            self.refresh_script_panel()
            self.refresh_current_preview()
        return "break"

    def cut_selected_dialogue_range(self, event=None):
        widget = getattr(event, "widget", None)
        widget_class = widget.winfo_class() if widget is not None else ""
        if widget_class in {"Entry", "Text"}:
            return "break"
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data() or row_idx not in dp.df.index:
            messagebox.showinfo(APP_TITLE, "請先選取要剪掉的句子。")
            return "break"
        time_col, _, _ = dp.get_columns()
        start, end = parse_time_range(dp.df.at[row_idx, time_col]) if time_col is not None else (None, None)
        if start is None or end is None or end <= start:
            messagebox.showinfo(APP_TITLE, "這句的時間格式無法剪片。")
            return "break"
        self.push_undo_state("剪去片段")
        self.renderer.set_cut_ranges(normalize_time_ranges(self.renderer.cut_ranges + [(start, end)]))
        if dp.delete_dialogue_row(row_idx):
            indices = self.dialogue_indices()
            self.selected_dialogue_row = indices[min(len(indices) - 1, max(0, row_idx))] if indices else None
            self.renderer.bubble_cache.clear()
            self.refresh_script_panel()
            self.refresh_current_preview()
            self.log(f"已標記剪去 {format_timecode(start)} - {format_timecode(end)}。匯出時會移除該片段。")
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
