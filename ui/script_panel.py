"""ScriptPanelMixin — 右側腳本面板的建構、更新與互動。

改善：
- 「無講話」行壓縮顯示（僅時間 + 圖示，不顯示 entry）
- 修改說話者用 CTkComboBox，允許直接輸入新名稱
- select_dialogue_row 後自動捲動到該行
- refresh_script_panel 在行數不變時只更新內容，避免整體重建
"""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
import pandas as pd

from core.constants import SILENCE_SPEAKER
from core.utils import ToolTip, parse_time_range, seconds_to_frame


class ScriptPanelMixin:
    SPEAKER_PALETTE = [
        ("#173B45", "#38BDF8"),
        ("#3B2A50", "#A78BFA"),
        ("#23462F", "#4ADE80"),
        ("#4A341C", "#F59E0B"),
        ("#4A2638", "#F472B6"),
        ("#1F3F3A", "#2DD4BF"),
        ("#3E2D22", "#FB7185"),
        ("#29364D", "#60A5FA"),
    ]

    def speaker_palette(self, speaker: str, fallback_idx: int = 0) -> tuple[str, str]:
        speaker = str(speaker or "").strip()
        if speaker == SILENCE_SPEAKER:
            return "#252A34", "#64748B"
        key = sum(ord(ch) for ch in speaker) if speaker else int(fallback_idx)
        return self.SPEAKER_PALETTE[key % len(self.SPEAKER_PALETTE)]

    # ------------------------------------------------------------------ 建構
    def refresh_script_panel(self):
        if not hasattr(self, "script_scroll"):
            return
        for child in self.script_scroll.winfo_children():
            child.destroy()
        self.script_row_widgets = {}
        dp = self.renderer.data_processor
        self.refresh_script_action_buttons()
        if hasattr(self, "btn_save_data"):
            self.btn_save_data.configure(state="normal" if dp.has_data() else "disabled")
        if not dp.has_data():
            ctk.CTkLabel(self.script_scroll, text="尚未建立腳本", text_color="#AAAAAA", anchor="w").pack(
                fill="x", padx=8, pady=10
            )
            return
        time_col, speaker_col, text_col = dp.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            ctk.CTkLabel(self.script_scroll, text="腳本欄位不足", text_color="#FCA5A5").pack(fill="x", padx=8, pady=10)
            return

        speakers = self.get_person_speaker_options(refresh=True)
        # 更新過濾器選項
        filter_speakers = ["全部"] + [s for s in speakers if s != SILENCE_SPEAKER]
        if hasattr(self, "_filter_speaker_combo"):
            current = self._filter_speaker_var.get()
            self._filter_speaker_combo.configure(values=filter_speakers)
            if current not in filter_speakers:
                self._filter_speaker_var.set("全部")
        filter_text = ""
        filter_speaker = ""
        if hasattr(self, "_script_search_text"):
            filter_text = self._script_search_text.get().strip().lower()
        if hasattr(self, "_filter_speaker_var"):
            filter_speaker = self._filter_speaker_var.get().strip()
        self._script_row_loading = True
        for row_idx, row in dp.df.iterrows():
            if filter_text:
                text_val = "" if pd.isna(row[text_col]) else str(row[text_col]).strip().lower()
                if filter_text not in text_val:
                    continue
            if filter_speaker and filter_speaker != "全部":
                spk_val = "" if pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
                if spk_val != filter_speaker:
                    continue
            self._build_script_row(row_idx, row, speakers)

        self._script_row_loading = False
        self.update_script_selection_styles()
        self.refresh_script_action_buttons()

    def _build_script_row(self, row_idx, row, speakers=None, after_widget=None):
        dp = self.renderer.data_processor
        time_col, speaker_col, text_col = dp.get_columns()
        speakers = speakers if speakers is not None else self.get_person_speaker_options()
        speaker = "" if pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
        text = "" if pd.isna(row[text_col]) else str(row[text_col]).strip()
        time_text = "" if pd.isna(row[time_col]) else str(row[time_col]).strip()
        is_selected = row_idx == self.selected_dialogue_row
        is_silence = speaker == SILENCE_SPEAKER
        is_deleted = dp.is_deleted(row_idx)

        _, speaker_accent = self.speaker_palette(speaker, row_idx)
        bg = "#3D2025" if is_deleted else ("#383838" if is_selected else "#2D2D2D")
        line = ctk.CTkFrame(
            self.script_scroll, fg_color=bg,
            border_width=1 if is_selected else 0, border_color="#46A3FF" if is_selected else "#2D2D2D",
        )
        pack_kwargs = {"fill": "x", "padx": 2, "pady": (0 if is_silence else 2)}
        if after_widget is not None and after_widget.winfo_exists():
            pack_kwargs["after"] = after_widget
        line.pack(**pack_kwargs)
        line.grid_columnconfigure(1, weight=1)
        # 說話者色條指示器（左側 3px 垂直色條）
        gutter_color = "#999999" if is_deleted else ("#666666" if is_silence else speaker_accent)
        gutter = ctk.CTkFrame(line, width=3, corner_radius=0, fg_color=gutter_color)
        gutter.place(x=0, y=2, relheight=1.0)
        strike_font = ctk.CTkFont(family="Microsoft JhengHei UI", size=11, overstrike=True)
        small_strike_font = ctk.CTkFont(family="Microsoft JhengHei UI", size=10, overstrike=True)
        text_color = "#AAAAAA" if is_deleted else None

        time_btn = ctk.CTkButton(
            line, text=time_text or "--:--",
            width=84, height=22 if is_silence else 24,
            fg_color="#3D2025" if is_deleted else "#383838",
            hover_color="#4A2A30" if is_deleted else "#4A4A4A",
            command=lambda idx=row_idx: self.select_dialogue_row(idx, seek=True, scroll=False),
        )
        time_btn.grid(row=0, column=0, padx=(4, 2), pady=(3 if is_silence else 4, 1 if is_silence else 1), sticky="w")

        if is_deleted:
            ctk.CTkLabel(
                line, text=speaker or "未命名",
                text_color=text_color, anchor="w",
                font=small_strike_font,
            ).grid(row=0, column=1, padx=2, pady=(4, 1), sticky="ew")
            restore_btn = ctk.CTkButton(
                line, text="↩", width=24, height=22,
                command=lambda idx=row_idx: self.restore_dialogue_from_panel(idx),
            )
            restore_btn.grid(row=0, column=2, padx=(2, 4), pady=(4, 1), sticky="e")
            ToolTip(restore_btn, "還原此句")
            ctk.CTkLabel(
                line, text=text or "（空白）",
                text_color=text_color, anchor="w",
                font=strike_font,
            ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=(1, 4))
            line.bind("<Button-1>", lambda _e, idx=row_idx: self.select_dialogue_row(idx, seek=True, scroll=False))
            self.script_row_widgets[row_idx] = {"frame": line, "time": time_btn, "text": None, "speaker": None, "gutter": gutter, "deleted_layout": True}
            return line

        if is_silence:
            ctk.CTkLabel(
                line, text="〈無講話〉",
                text_color="#888888", anchor="w",
                font=("Microsoft JhengHei UI", 10),
            ).grid(row=0, column=1, padx=2, pady=3, sticky="w")
            silence_del_btn = ctk.CTkButton(
                line, text="✕", width=22, height=22,
                command=lambda idx=row_idx: self.delete_dialogue_from_panel(idx),
            )
            silence_del_btn.grid(row=0, column=2, padx=(2, 4), pady=3, sticky="e")
            ToolTip(silence_del_btn, "刪除此句")
            line.bind("<Button-1>", lambda _e, idx=row_idx: self.select_dialogue_row(idx, seek=True, scroll=False))
            self.script_row_widgets[row_idx] = {"frame": line, "time": time_btn, "text": None, "speaker": None, "gutter": gutter, "deleted_layout": False}
            return line

        combo_values = [s for s in speakers if s != SILENCE_SPEAKER] or ["人物 1"]
        speaker_var = ctk.StringVar(value=speaker)
        speaker_combo = ctk.CTkComboBox(
            line, values=combo_values,
            variable=speaker_var,
            width=100, height=24,
            command=lambda value, idx=row_idx: self.change_script_row_speaker(idx, value),
        )
        speaker_combo.set(speaker)
        speaker_combo.configure(border_color=speaker_accent, button_color=speaker_accent)
        speaker_combo.grid(row=0, column=1, padx=2, pady=(4, 1), sticky="ew")
        speaker_combo.bind(
            "<FocusOut>",
            lambda _e, idx=row_idx, var=speaker_var: self.change_script_row_speaker(idx, var.get()),
        )
        speaker_combo.bind(
            "<Return>",
            lambda _e, idx=row_idx, var=speaker_var: self.change_script_row_speaker(idx, var.get()),
        )

        ops = ctk.CTkFrame(line, fg_color="transparent")
        ops.grid(row=0, column=2, padx=(2, 4), pady=(4, 1), sticky="e")
        play_btn = ctk.CTkButton(ops, text="▶", width=24, height=22,
                                 command=lambda idx=row_idx: self.play_dialogue_row(idx))
        play_btn.pack(side="left", padx=1)
        ToolTip(play_btn, "播放此句")
        merge_btn = ctk.CTkButton(ops, text="⤒", width=24, height=22,
                                  command=lambda idx=row_idx: self.merge_dialogue_from_panel(idx))
        merge_btn.pack(side="left", padx=1)
        ToolTip(merge_btn, "合併至上一句")
        delete_btn = ctk.CTkButton(ops, text="✕", width=24, height=22,
                                   command=lambda idx=row_idx: self.delete_dialogue_from_panel(idx))
        delete_btn.pack(side="left", padx=1)
        ToolTip(delete_btn, "刪除此句")

        text_entry = ctk.CTkEntry(line, border_color=speaker_accent)
        text_entry.insert(0, text)
        text_entry.grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=(1, 4))
        text_entry.bind("<FocusIn>", lambda _e, idx=row_idx: self.select_dialogue_row_for_edit(idx))
        text_entry.bind("<KeyRelease>", lambda _e, idx=row_idx, entry=text_entry: self.update_script_row_text(idx, entry.get()))
        line.bind("<Button-1>", lambda _e, idx=row_idx: self.select_dialogue_row(idx, seek=True, scroll=False))

        self.script_row_widgets[row_idx] = {
            "frame": line,
            "time": time_btn,
            "text": text_entry,
            "speaker": speaker_var,
            "gutter": gutter,
            "delete_button": delete_btn,
            "deleted_layout": False,
            "normal_font": text_entry.cget("font"),
            "normal_text_color": text_entry.cget("text_color"),
        }
        return line

    def refresh_script_action_buttons(self):
        dp = self.renderer.data_processor
        has_data = dp.has_data()
        has_video = bool(getattr(self.renderer, "video_path", None))
        selected = self.selected_dialogue_row
        has_selected = has_data and selected is not None and selected in dp.df.index
        selected_deleted = has_selected and dp.is_deleted(selected)
        button_states = {
            "btn_add_sentence": "normal" if has_video else "disabled",
            "btn_split": "normal" if has_selected and not selected_deleted else "disabled",
            "btn_merge": "normal" if has_selected and not selected_deleted else "disabled",
            "btn_delete_dialogue": "normal" if has_selected and not selected_deleted else "disabled",
            "btn_restore_delete": "normal" if selected_deleted else "disabled",
        }
        for name, state in button_states.items():
            button = getattr(self, name, None)
            if button is not None:
                button.configure(state=state)

    # ------------------------------------------------------------------ 選取樣式
    def update_script_selection_styles(self, row_indices=None):
        if not hasattr(self, "script_row_widgets"):
            return
        dp = self.renderer.data_processor
        time_col, speaker_col, _ = dp.get_columns() if dp.has_data() else (None, None, None)
        if row_indices is None:
            items = self.script_row_widgets.items()
        else:
            row_indices = set(row_indices)
            last_styled = getattr(self, "_last_styled_dialogue_row", None)
            if last_styled is not None:
                row_indices.add(last_styled)
            if self.selected_dialogue_row is not None:
                row_indices.add(self.selected_dialogue_row)
            items = (
                (row_idx, self.script_row_widgets.get(row_idx))
                for row_idx in row_indices
                if row_idx in self.script_row_widgets
            )
        for row_idx, widgets in items:
            if not widgets:
                continue
            frame = widgets.get("frame")
            if frame is None or not frame.winfo_exists():
                continue
            is_selected = row_idx == self.selected_dialogue_row
            speaker = ""
            if speaker_col is not None and dp.has_data() and row_idx in dp.df.index:
                value = dp.df.at[row_idx, speaker_col]
                speaker = "" if pd.isna(value) else str(value).strip()
            is_silence = speaker == SILENCE_SPEAKER
            is_deleted = dp.is_deleted(row_idx)
            _, speaker_accent = self.speaker_palette(speaker, row_idx)
            bg = "#4A2630" if is_deleted else ("#28364A" if is_selected else "#1E2433")
            try:
                frame.configure(fg_color=bg, border_width=1 if is_selected else 0, border_color="#FBBF24" if is_selected else "#1E2433")
            except Exception:
                frame.configure(fg_color=bg)
            gutter = widgets.get("gutter")
            if gutter is not None and gutter.winfo_exists():
                gutter_color = "#6B7280" if is_deleted else ("#4B5563" if is_silence else speaker_accent)
                try:
                    gutter.configure(fg_color=gutter_color)
                except Exception:
                    pass
        self._last_styled_dialogue_row = self.selected_dialogue_row

    def update_script_row_deleted_state(self, row_idx) -> bool:
        widgets = getattr(self, "script_row_widgets", {}).get(row_idx)
        if not widgets:
            return False
        dp = self.renderer.data_processor
        frame = widgets.get("frame")
        if frame is None or not frame.winfo_exists():
            return False
        is_deleted = dp.is_deleted(row_idx)
        if not is_deleted and widgets.get("deleted_layout"):
            return False
        is_selected = row_idx == self.selected_dialogue_row
        speaker = ""
        _, speaker_col, _ = dp.get_columns() if dp.has_data() else (None, None, None)
        if speaker_col is not None and row_idx in dp.df.index:
            value = dp.df.at[row_idx, speaker_col]
            speaker = "" if pd.isna(value) else str(value).strip()
        _, speaker_accent = self.speaker_palette(speaker, row_idx)
        bg = "#4A2630" if is_deleted else ("#28364A" if is_selected else "#1E2433")
        try:
            frame.configure(fg_color=bg, border_width=1 if is_selected else 0, border_color="#FBBF24" if is_selected else "#1E2433")
        except Exception:
            frame.configure(fg_color=bg)
        gutter = widgets.get("gutter")
        if gutter is not None and gutter.winfo_exists():
            gutter_color = "#6B7280" if is_deleted else speaker_accent
            try:
                gutter.configure(fg_color=gutter_color)
            except Exception:
                pass
        text_entry = widgets.get("text")
        if text_entry is not None and text_entry.winfo_exists():
            if is_deleted:
                text_entry.configure(
                    font=ctk.CTkFont(family="Microsoft JhengHei UI", size=12, overstrike=True),
                    text_color="#AAAAAA",
                )
            else:
                text_entry.configure(font=widgets.get("normal_font"), text_color=widgets.get("normal_text_color"))
        delete_btn = widgets.get("delete_button")
        if delete_btn is not None and delete_btn.winfo_exists():
            if is_deleted:
                delete_btn.configure(text="↩")
            else:
                delete_btn.configure(text="✕")
        return True

    # ------------------------------------------------------------------ 自動捲動
    def _scroll_to_selected_row(self):
        if self.selected_dialogue_row not in self.script_row_widgets:
            return
        widgets = self.script_row_widgets.get(self.selected_dialogue_row)
        if not widgets:
            return
        frame = widgets.get("frame")
        if frame is None or not frame.winfo_exists():
            return
        self.after(60, lambda: self._do_scroll_to_widget(frame))

    def _do_scroll_to_widget(self, frame):
        try:
            canvas = self.script_scroll._parent_canvas
            bbox = canvas.bbox("all")
            if not bbox:
                return
            content_h = bbox[3]          # 全部內容高度（scrollregion）
            canvas_h = canvas.winfo_height()
            if content_h <= canvas_h:
                return
            fy = frame.winfo_y()         # row 在 content 裡的 y 位置
            target = max(0.0, min(1.0, (fy - canvas_h * 0.30) / content_h))
            canvas.yview_moveto(target)
        except Exception:
            pass

    def _focus_waveform_on_dialogue(self, row_idx, start=None, end=None):
        if start is None or end is None:
            dp = self.renderer.data_processor
            time_col, _, _ = dp.get_columns()
            if time_col is None or row_idx not in dp.df.index:
                return
            start, end = parse_time_range(dp.df.at[row_idx, time_col])
        if start is None or end is None or not hasattr(self, "get_waveform_timeline_duration"):
            return
        duration = self.get_waveform_timeline_duration()
        if duration <= 0:
            return
        view_start, view_end = self.get_waveform_view_range()
        span = max(0.5, view_end - view_start)
        margin = min(0.5, span * 0.12)
        if start >= view_start + margin and end <= view_end - margin:
            return
        center = (start + end) / 2
        new_start = max(0.0, min(duration - span, center - span / 2))
        self.waveform_view_start = new_start
        self.waveform_view_end = new_start + span

    def update_script_row_time_display(self, row_idx):
        widgets = getattr(self, "script_row_widgets", {}).get(row_idx)
        if not widgets:
            return
        time_btn = widgets.get("time")
        if time_btn is None or not time_btn.winfo_exists():
            return
        dp = self.renderer.data_processor
        time_col, _, _ = dp.get_columns()
        if time_col is None or row_idx not in dp.df.index:
            return
        value = dp.df.at[row_idx, time_col]
        time_text = "" if pd.isna(value) else str(value).strip()
        time_btn.configure(text=time_text or "--:--")

    def update_script_row_from_data(self, row_idx) -> bool:
        widgets = getattr(self, "script_row_widgets", {}).get(row_idx)
        dp = self.renderer.data_processor
        if not widgets or not dp.has_data() or row_idx not in dp.df.index:
            return False
        time_col, speaker_col, text_col = dp.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            return False
        self.update_script_row_time_display(row_idx)
        row = dp.df.loc[row_idx]
        speaker = "" if pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
        text = "" if pd.isna(row[text_col]) else str(row[text_col]).strip()
        speaker_var = widgets.get("speaker")
        if speaker_var is not None:
            speaker_var.set(speaker)
        text_entry = widgets.get("text")
        if text_entry is not None and text_entry.winfo_exists() and text_entry.get() != text:
            self._script_row_loading = True
            text_entry.delete(0, "end")
            text_entry.insert(0, text)
            self._script_row_loading = False
        return True

    def insert_script_row_from_data(self, row_idx, after_row_idx=None) -> bool:
        dp = self.renderer.data_processor
        if not dp.has_data() or row_idx not in dp.df.index:
            return False
        after_widget = None
        if after_row_idx is not None:
            after_widgets = getattr(self, "script_row_widgets", {}).get(after_row_idx)
            after_widget = after_widgets.get("frame") if after_widgets else None
        self._script_row_loading = True
        self._build_script_row(row_idx, dp.df.loc[row_idx], self.get_person_speaker_options(), after_widget=after_widget)
        self._script_row_loading = False
        return True

    # ------------------------------------------------------------------ 當前句顯示
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

    # ------------------------------------------------------------------ 選取列
    def selected_script_text_widget(self):
        widgets = getattr(self, "script_row_widgets", {}).get(self.selected_dialogue_row)
        if not widgets:
            return None
        entry = widgets.get("text")
        if entry is not None and entry.winfo_exists():
            return entry
        return None

    def select_dialogue_row_for_edit(self, row_idx):
        self._suppress_select_waveform_redraw = True
        try:
            self.select_dialogue_row(row_idx, seek=False, scroll=False)
        finally:
            self._suppress_select_waveform_redraw = False

    def current_dialogue_text_and_cursor(self):
        """優先使用右側腳本面板 entry 的文字與游標位置。"""
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

    def select_dialogue_row(self, row_idx, seek: bool = True, scroll: bool = True, redraw_waveform: bool = True):
        dp = self.renderer.data_processor
        if not dp.has_data() or row_idx is None or row_idx not in dp.df.index:
            return
        previous_row = self.selected_dialogue_row
        time_col, _, _ = dp.get_columns()
        start, end = parse_time_range(dp.df.at[row_idx, time_col]) if time_col is not None else (None, None)
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
        self.refresh_script_action_buttons()
        if seek and start is not None and self.renderer.total_frames:
            self._focus_waveform_on_dialogue(row_idx, start, end)
            # +0.05s 避免浮點取整落在對話起始幀前一格
            frame = seconds_to_frame(start + 0.05, self.renderer.fps, self.renderer.total_frames)
            self.stop_preview_playback()
            if self.slider_timeline.cget("state") == "normal":
                self.slider_timeline.set(frame)
            self.update_timecode_and_waveform(frame)
            self._render_scrub(frame)
        elif redraw_waveform and not getattr(self, "_suppress_select_waveform_redraw", False):
            self.draw_waveform(self.current_frame())
        self.update_script_selection_styles({previous_row, row_idx})
        if scroll:
            self._scroll_to_selected_row()

    # ------------------------------------------------------------------ 修改
    def change_script_row_speaker(self, row_idx, speaker: str):
        if self._script_row_loading:
            return
        speaker = speaker.strip()
        if not speaker:
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
            self._script_speaker_options_cache = None
            self.renderer.bubble_cache.clear()
            self.update_script_selection_styles({row_idx})
            self.refresh_current_preview()

    def update_script_row_text(self, row_idx, text: str):
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
            self.update_current_sentence_label()
            self.schedule_script_preview_refresh(delay_ms=450)

    def schedule_script_preview_refresh(self, delay_ms: int = 180):
        if self.slider_timeline.cget("state") != "normal":
            return
        after_id = getattr(self, "_script_preview_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._script_preview_after_id = self.after(delay_ms, self._run_script_preview_refresh)

    def _run_script_preview_refresh(self):
        self._script_preview_after_id = None
        self.refresh_current_preview()

    def delete_dialogue_from_panel(self, row_idx):
        self.selected_dialogue_row = row_idx
        self.delete_selected_dialogue()

    def restore_dialogue_from_panel(self, row_idx):
        self.selected_dialogue_row = row_idx
        self.delete_selected_dialogue()

    def merge_dialogue_from_panel(self, row_idx):
        self.selected_dialogue_row = row_idx
        self.merge_selected_dialogue()

    def play_dialogue_row(self, row_idx):
        dp = self.renderer.data_processor
        if not dp.has_data() or row_idx not in dp.df.index:
            return "break"
        time_col, _, _ = dp.get_columns()
        if time_col is None:
            return "break"
        start, end = parse_time_range(dp.df.at[row_idx, time_col])
        if start is None or end is None:
            return "break"
        self.select_dialogue_row(row_idx, seek=False, scroll=False, redraw_waveform=False)
        self.start_preview_range(start, end)
        return "break"

    def delete_selected_from_toolbar(self):
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data() or row_idx not in dp.df.index or dp.is_deleted(row_idx):
            return "break"
        return self.delete_selected_dialogue()

    def restore_selected_from_toolbar(self):
        dp = self.renderer.data_processor
        row_idx = self.selected_dialogue_row
        if row_idx is None or not dp.has_data() or row_idx not in dp.df.index or not dp.is_deleted(row_idx):
            return "break"
        return self.delete_selected_dialogue()

    # ------------------------------------------------------------------ 說話者選項
    def get_person_speaker_options(self, refresh: bool = False) -> list[str]:
        if not refresh:
            cached = getattr(self, "_script_speaker_options_cache", None)
            if cached is not None:
                return list(cached)
        count = max(len(self.renderer.person_rois), self.renderer.expected_people_count, 1)
        unique = []
        for idx in range(1, count + 1):
            name = self.renderer.yolo_id_to_speaker.get(idx, f"人物 {idx}")
            if name and name not in unique:
                unique.append(name)
        for value in self.renderer.data_processor.get_unique_speakers():
            if value and value not in unique:
                unique.append(value)
        unique.append(SILENCE_SPEAKER)
        self._script_speaker_options_cache = list(unique)
        return unique
