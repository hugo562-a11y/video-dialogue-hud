"""App — 主視窗，繼承所有 Mixin 並建構 UI。"""
from __future__ import annotations

import queue
import tkinter as tk

import customtkinter as ctk

from core.constants import APP_TITLE, MIN_SILENCE_SECONDS
from core.utils import ToolTip
from core.video_renderer import VideoRenderer
from ui.controls import ControlsMixin
from ui.editing import EditingMixin
from ui.preview import PreviewMixin
from ui.script_panel import ScriptPanelMixin
from ui.waveform import WaveformMixin
from ui.workflow import WorkflowMixin


class App(
    WaveformMixin,
    PreviewMixin,
    ScriptPanelMixin,
    ControlsMixin,
    EditingMixin,
    WorkflowMixin,
    ctk.CTk,
):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1500x860")
        self.minsize(1180, 720)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("adobe_theme.json")
        self.configure(fg_color="#1E1E1E")

        self.renderer = VideoRenderer(ui_callback=self.handle_renderer_update)
        self.ui_queue = queue.Queue()

        # 預覽畫布狀態
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
        self._adjust_box_drag_tid = None
        self._adjust_box_orig_bbox = None
        self._adjust_box_corner = None   # "tl","tr","bl","br" = resize corner; None = move
        self.preview_boxes = []
        self.preview_scale_x = 1.0
        self.preview_scale_y = 1.0

        # 工作流程狀態
        self.people_count_confirmed = False
        self.selected_dialogue_row = None
        self._loading_person_fields = False
        self.audio_scrub_var = ctk.BooleanVar(value=True)
        self.silence_seconds_var = ctk.DoubleVar(value=MIN_SILENCE_SECONDS)

        # 音訊
        self._ffplay_process = None
        self._waveform_audio_path = None
        self._last_audio_preview_at = -1.0

        self._show_person_boxes = True   # 顯示/隱藏人物框

        # 聲波
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

        # 播放
        self.preview_playing = False
        self._preview_play_after_id = None
        self._preview_play_start_frame = 1
        self._preview_play_start_time = 0.0
        self._preview_request_id = 0
        self._preview_render_pending = False
        self._last_preview_render_time = 0.0
        self._script_preview_after_id = None

        # Undo/Redo
        self.undo_stack = []
        self.redo_stack = []
        self._undo_limit = 80
        self._typing_undo_row = None
        self._typing_undo_original = None
        self._waveform_undo_pushed = False

        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<space>", self.toggle_preview_playback)
        self.bind_all("<Left>", lambda e: self.step_playhead(-1, e))
        self.bind_all("<Right>", lambda e: self.step_playhead(1, e))
        self.bind_all("<Control-z>", self.undo_action)
        self.bind_all("<Control-y>", self.redo_action)
        self.bind_all("<Up>", lambda e: self.step_dialogue(-1, e))
        self.bind_all("<Down>", lambda e: self.step_dialogue(1, e))
        self.bind_all("<Home>", self.seek_home)
        self.bind_all("<End>", self.seek_end)
        self.bind_all("<Control-Return>", lambda e: (self.split_current_sentence(), "break")[1])
        self.bind_all("<Control-KP_Enter>", lambda e: (self.split_current_sentence(), "break")[1])
        self.bind_all("<Return>", self.play_current_sentence)
        self.bind_all("<Delete>", self.delete_selected_dialogue)
        self.bind_all("<bracketleft>", lambda e: self.nudge_dialogue_edge("start", -0.05, e))
        self.bind_all("<bracketright>", lambda e: self.nudge_dialogue_edge("end", 0.05, e))
        self.bind_all("<Shift-bracketleft>", lambda e: self.nudge_dialogue_edge("start", 0.05, e))
        self.bind_all("<Shift-bracketright>", lambda e: self.nudge_dialogue_edge("end", -0.05, e))
        self.bind_all("<question>", self.show_shortcut_help)
        self.bind_all("<Key-slash>", self.show_shortcut_help)
        self.check_queue()

    def setup_ui(self):
        self.script_row_widgets = {}
        self._script_row_loading = False
        self._log_expanded = True

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        paned = tk.PanedWindow(self, orient="horizontal", bg="#2D2D2D", sashwidth=1, sashrelief="flat", sashpad=0)
        paned.pack(fill="both", expand=True, padx=0, pady=0)

        # ---- 左側邊欄 ----
        sidebar = ctk.CTkFrame(paned, width=220, fg_color="#252525")
        paned.add(sidebar, minsize=140, width=220, stretch="never")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(sidebar, text="影片對話 HUD", font=("Microsoft JhengHei UI", 15, "bold")).pack(
            fill="x", padx=10, pady=(12, 1)
        )
        ctk.CTkLabel(sidebar, text="校稿工作台", text_color="#AAAAAA", anchor="w").pack(
            fill="x", padx=10, pady=(0, 10)
        )

        self._section_expanded = {"import": True, "speech": True, "people": True, "export": True}
        self._section_frames = {}
        self.workflow_group_labels = {}

        def make_section_toggle(key, text, color="#AAAAAA", pady_top=4):
            frame = ctk.CTkFrame(sidebar, fg_color="transparent")
            frame.pack(fill="x", padx=10, pady=(pady_top, 0))
            lbl = ctk.CTkLabel(frame, text=f"▼ {text}", anchor="w",
                               font=("Microsoft JhengHei UI", 11, "bold"), text_color=color,
                               cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda _e, k=key: _toggle_section(k))
            self.workflow_group_labels[key] = lbl
            return frame

        def _toggle_section(key):
            self._section_expanded[key] = not self._section_expanded[key]
            sf = self._section_frames.get(key)
            lbl = self.workflow_group_labels.get(key)
            if sf is not None:
                if self._section_expanded[key]:
                    sf.pack(fill="x", padx=0, pady=0)
                else:
                    sf.pack_forget()
            if lbl is not None:
                arrow = "▼" if self._section_expanded[key] else "▶"
                text = lbl.cget("text")
                text = text[1:].strip() if text[0] in "▶▼" else text
                lbl.configure(text=f"{arrow} {text}")

        # ---- 1. 匯入與代理檔 ----
        make_section_toggle("import", "1. 匯入與代理檔", color="#46A3FF", pady_top=0)
        import_section = ctk.CTkFrame(sidebar, fg_color="transparent")
        import_section.pack(fill="x", padx=0, pady=0)
        import_section.grid_columnconfigure(0, weight=1)
        self._section_frames["import"] = import_section
        self.btn_video = ctk.CTkButton(import_section, text="選擇影片", command=self.select_video, height=26)
        self.btn_video.grid(row=0, column=0, sticky="ew", padx=10, pady=2)

        # ---- 2. 聲音與腳本 ----
        make_section_toggle("speech", "2. 聲音與腳本")
        speech_section = ctk.CTkFrame(sidebar, fg_color="transparent")
        speech_section.pack(fill="x", padx=0, pady=0)
        speech_section.grid_columnconfigure(0, weight=1)
        self._section_frames["speech"] = speech_section
        self.btn_speech = ctk.CTkButton(
            speech_section, text="辨識聲音", command=self.generate_speech_script,
            height=26, state="disabled",
        )
        self.btn_speech.grid(row=0, column=0, sticky="ew", padx=10, pady=2)
        count_frame = ctk.CTkFrame(speech_section, fg_color="transparent")
        count_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 2))
        count_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(count_frame, text="人物數量：", font=("Microsoft JhengHei UI", 11)).grid(row=0, column=0, padx=(0, 6))
        self.person_count_var = ctk.StringVar(value="1")
        self.person_count_menu = ctk.CTkOptionMenu(
            count_frame, values=[str(i) for i in range(1, 13)],
            variable=self.person_count_var, command=self._on_person_count_change,
            width=60, height=24,
        )
        self.person_count_menu.grid(row=0, column=1, sticky="w")

        # ---- 3. 人物與掃描 ----
        make_section_toggle("people", "3. 人物與掃描", pady_top=4)
        people_section = ctk.CTkFrame(sidebar, fg_color="transparent")
        people_section.pack(fill="x", padx=0, pady=0)
        people_section.grid_columnconfigure(0, weight=1)
        self._section_frames["people"] = people_section
        self.btn_name_people = ctk.CTkButton(
            people_section, text="命名人物", command=self.open_person_namer,
            height=26, state="disabled",
        )
        self.btn_name_people.grid(row=0, column=0, sticky="ew", padx=10, pady=2)
        self.btn_draw_people = ctk.CTkButton(
            people_section, text="框選人物", command=self.start_person_box_mode, height=26, state="disabled"
        )
        self.btn_draw_people.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        person_tools = ctk.CTkFrame(people_section, fg_color="transparent")
        person_tools.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))
        person_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_confirm_people = ctk.CTkButton(
            person_tools, text="確認框選", command=self.confirm_people_count, height=24, state="disabled"
        )
        self.btn_confirm_people.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.btn_clear_people = ctk.CTkButton(
            person_tools, text="清除", command=self.clear_person_boxes, height=24,
            state="disabled",
        )
        self.btn_clear_people.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        self.btn_scan = ctk.CTkButton(
            people_section, text="掃描人物", command=self.start_preview_scan,
            height=26, state="disabled"
        )
        self.btn_scan.grid(row=3, column=0, sticky="ew", padx=10, pady=2)

        # ---- 4. 校稿與匯出 ----
        make_section_toggle("export", "4. 校稿與匯出", pady_top=4)
        export_section = ctk.CTkFrame(sidebar, fg_color="transparent")
        export_section.pack(fill="x", padx=0, pady=0)
        export_section.grid_columnconfigure(0, weight=1)
        self._section_frames["export"] = export_section
        self.btn_export_preview = ctk.CTkButton(
            export_section, text="匯出預覽", command=self.start_preview_export,
            height=24, state="disabled",
        )
        self.btn_export_preview.grid(row=0, column=0, sticky="ew", padx=10, pady=2)
        self.btn_export = ctk.CTkButton(
            export_section, text="匯出影片", command=self.start_export,
            height=26, state="disabled", fg_color="#27AE60", hover_color="#229954",
        )
        self.btn_export.grid(row=1, column=0, sticky="ew", padx=10, pady=2)

        # ---- 底部延伸區 ----
        ctk.CTkFrame(sidebar, fg_color="transparent").pack(fill="both", expand=True)

        self.progress_bar = ctk.CTkProgressBar(sidebar, height=4)
        self.progress_bar.pack(fill="x", padx=10, pady=(10, 0))
        self.progress_bar.set(0)
        self.lbl_progress = ctk.CTkLabel(
            sidebar, text="", anchor="e", font=("Consolas", 9),
            text_color="#AAAAAA",
        )
        self.lbl_progress.pack(fill="x", padx=(10, 12), pady=(1, 2))

        self.status_label = ctk.CTkLabel(
            sidebar, text="尚未選擇影片", anchor="w", justify="left", wraplength=180
        )
        self.status_label.configure(text="先選擇影片，工具會建立 720 proxy。", wraplength=180)
        self.status_label.pack(fill="x", padx=10, pady=(0, 6))

        self.btn_open_export = ctk.CTkButton(
            sidebar, text="開啟輸出影片", command=self.open_export_video,
            height=24, state="disabled",
        )
        self.btn_open_export.pack(fill="x", padx=10, pady=(2, 1))

        self.export_path_label = ctk.CTkLabel(
            sidebar, text="", anchor="w", justify="left",
            wraplength=180, font=("Microsoft JhengHei UI", 10),
            text_color="#AAAAAA", cursor="hand2",
        )
        self.export_path_label.pack(fill="x", padx=10, pady=(0, 2))
        self.export_path_label.bind("<Button-1>", lambda _e: self.open_export_video())

        self.log_box = ctk.CTkTextbox(sidebar, wrap="word", height=120)
        self.log_box.pack(fill="x", padx=10, pady=(2, 8))
        self.log_box.bind("<Key>", lambda e: "break")

        self.btn_toggle_log = ctk.CTkButton(
            sidebar, text="隱藏記錄", command=self.toggle_log_panel,
            height=24,
        )
        self.btn_toggle_log.pack(fill="x", padx=10, pady=(0, 4))

        # ---- 中央主區域 ----
        main = ctk.CTkFrame(paned, fg_color="#1E1E1E")
        paned.add(main, minsize=400, stretch="always")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(2, weight=0)

        # 頂部設定列
        controls = ctk.CTkFrame(main, fg_color="#2D2D2D")
        controls.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 1))
        controls.grid_columnconfigure(4, weight=1)

        # 邏輯用欄位（不可見，仍持有資料）
        self.entry_id = ctk.CTkEntry(controls, width=1)
        self.entry_id.insert(0, "1")
        self.entry_speaker = ctk.CTkEntry(controls, width=1)
        self.entry_text = ctk.CTkEntry(controls, width=1)

        # 設定群組：辨識
        grp_asr = ctk.CTkFrame(controls, fg_color="transparent")
        grp_asr.grid(row=0, column=0, sticky="w", padx=(4, 4), pady=(4, 2))
        ctk.CTkLabel(grp_asr, text="辨識", anchor="w", font=("Microsoft JhengHei UI", 11)).pack(side="left", padx=(4, 4))
        self.whisper_model_var = ctk.StringVar(value="medium")
        self.whisper_menu = ctk.CTkOptionMenu(
            grp_asr, values=["base", "small", "medium", "large-v3"],
            variable=self.whisper_model_var, width=90, height=24, state="disabled",
        )
        self.whisper_menu.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(grp_asr, text="無講話", anchor="w", font=("Microsoft JhengHei UI", 11)).pack(side="left", padx=(0, 4))
        self.silence_slider = ctk.CTkSlider(
            grp_asr, from_=0.2, to=1.5, number_of_steps=13, width=80,
            variable=self.silence_seconds_var, height=14,
        )
        self.silence_slider.pack(side="left", padx=(0, 4))
        self.lbl_silence = ctk.CTkLabel(grp_asr, text="0.45s", width=36)
        self.lbl_silence.pack(side="left", padx=(0, 4))
        self.silence_slider.configure(command=lambda v: self.lbl_silence.configure(text=f"{float(v):.2f}s"))

        # 設定群組：字級
        grp_font = ctk.CTkFrame(controls, fg_color="transparent")
        grp_font.grid(row=0, column=1, sticky="w", padx=6, pady=(4, 2))
        ctk.CTkLabel(grp_font, text="字級", anchor="w", font=("Microsoft JhengHei UI", 11)).pack(side="left", padx=(0, 4))
        self.slider_font_size = ctk.CTkSlider(grp_font, from_=18, to=180, width=100, height=14, command=self.update_style)
        self.slider_font_size.set(72)
        self.slider_font_size.pack(side="left")

        # 設定群組：播放
        grp_play = ctk.CTkFrame(controls, fg_color="transparent")
        grp_play.grid(row=0, column=2, sticky="w", padx=6, pady=(4, 2))
        self.audio_scrub_check = ctk.CTkCheckBox(
            grp_play, text="聲波定位", variable=self.audio_scrub_var,
        )
        self.audio_scrub_check.pack(side="left", padx=(0, 6))
        self.btn_undo = ctk.CTkButton(grp_play, text="↩", width=44, height=26, command=self.undo_action)
        self.btn_undo.pack(side="left", padx=1)
        ToolTip(self.btn_undo, "復原  Ctrl+Z")
        self.btn_redo = ctk.CTkButton(grp_play, text="↪", width=44, height=26, command=self.redo_action)
        self.btn_redo.pack(side="left", padx=1)
        ToolTip(self.btn_redo, "重做  Ctrl+Y")

        self.current_sentence_label = ctk.CTkLabel(
            controls, text="在右側腳本列表修改文字與說話者",
            anchor="w",             text_color="#AAAAAA", font=("Microsoft JhengHei UI", 11),
        )
        self.current_sentence_label.grid(row=1, column=0, columnspan=6, sticky="ew", padx=(8, 8), pady=(1, 2))

        self.shortcut_label = ctk.CTkLabel(
            controls,
            text="Space 播放  |  Enter 播當前句  |  ↑↓ 上/下一句  |  ←→ 逐幀  |  [ ] 微調邊界  |  Ctrl+Enter 斷句  |  Ctrl+Z/Y 復原/重做  |  Del 刪/還  |  Home/End 頭尾  |  ? 快捷鍵",
            anchor="w",             text_color="#888888", font=("Microsoft JhengHei UI", 10),
        )
        self.shortcut_label.grid(row=2, column=0, columnspan=6, sticky="ew", padx=(8, 8), pady=(0, 4))

        # 預覽畫布
        canvas_frame = ctk.CTkFrame(main, fg_color="#1E1E1E")
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.preview_canvas = tk.Canvas(
            canvas_frame, bg="#1E1E1E", highlightthickness=0, cursor="crosshair", takefocus=1
        )
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.create_text(420, 240, text="選擇影片後會顯示預覽", fill="#888888", font=("Microsoft JhengHei UI", 16))
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_scroll)
        self.preview_canvas.bind("<ButtonPress-1>", self._on_canvas_drag_start)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.preview_canvas.bind("<ButtonPress-3>", self._on_canvas_right_click)
        self.preview_canvas.bind("<Motion>", self._on_canvas_motion)

        # 時間軸列
        tool_row = ctk.CTkFrame(main, fg_color="#2D2D2D")
        tool_row.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        tool_row.grid_columnconfigure(1, weight=1)

        self.lbl_timecode = ctk.CTkLabel(
            tool_row, text="00:00", width=60, font=("Consolas", 13, "bold"), text_color="#46A3FF"
        )
        self.lbl_timecode.grid(row=0, column=0, sticky="w", padx=(6, 4), pady=(6, 2))

        # 播放按鈕
        _btn_row = ctk.CTkFrame(tool_row, fg_color="transparent")
        _btn_row.grid(row=0, column=1, sticky="w", padx=2, pady=(4, 2))
        self.btn_play_all = ctk.CTkButton(
            _btn_row, text="▶ 全部", width=72, height=24,
            command=lambda: self.start_preview_playback(play_edited=False),
            state="disabled",
        )
        self.btn_play_all.pack(side="left", padx=(0, 2))
        self.btn_play_edited = ctk.CTkButton(
            _btn_row, text="▶ 剪後", width=68, height=24,
            command=lambda: self.start_preview_playback(play_edited=True),
            state="disabled",
        )
        self.btn_play_edited.pack(side="left", padx=(0, 4))

        self.btn_toggle_boxes = ctk.CTkButton(
            _btn_row, text="人物框", width=64, height=24,
            command=self._toggle_person_boxes,
        )
        self.btn_toggle_boxes.pack(side="left", padx=(0, 2))

        self.btn_adjust_boxes = ctk.CTkButton(
            _btn_row, text="框位", width=56, height=24,
            command=self._toggle_adjust_box_mode,
        )
        self.btn_adjust_boxes.pack(side="left", padx=(0, 2))

        self.btn_rescan_here = ctk.CTkButton(
            _btn_row, text="追蹤", width=56, height=24,
            command=self.start_rescan_from_here,
            state="disabled",
        )
        self.btn_rescan_here.pack(side="left")

        # 時間資訊：播放頭 | 剪後時長 | 全部時長
        self.lbl_duration_info = ctk.CTkLabel(
            tool_row, text="", font=("Consolas", 10),             text_color="#AAAAAA", anchor="e"
        )
        self.lbl_duration_info.grid(row=0, column=2, sticky="e", padx=(4, 8), pady=(6, 2))

        self.slider_timeline = ctk.CTkSlider(
            tool_row, from_=1, to=1, command=self.on_timeline_scrub, state="disabled",
            height=14,
        )
        self.slider_timeline.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(1, 0))
        self.slider_timeline.bind("<Button-1>", self._on_slider_press, add=True)
        self.slider_timeline.bind("<B1-Motion>", self._on_slider_drag, add=True)
        self.slider_timeline.bind("<ButtonRelease-1>", self._on_slider_release, add=True)

        self.waveform_canvas = tk.Canvas(tool_row, height=100, bg="#252525", highlightthickness=0)
        self.waveform_canvas.grid(row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=(2, 6))
        self.waveform_canvas.bind("<Button-1>", self.on_waveform_click)
        self.waveform_canvas.bind("<B1-Motion>", self.on_waveform_drag)
        self.waveform_canvas.bind("<ButtonRelease-1>", self.on_waveform_release)
        self.waveform_canvas.bind("<Button-3>", self.on_waveform_pan_start)
        self.waveform_canvas.bind("<B3-Motion>", self.on_waveform_pan_drag)
        self.waveform_canvas.bind("<ButtonRelease-3>", self.on_waveform_pan_release)
        self.waveform_canvas.bind("<Motion>", self.on_waveform_motion)
        self.waveform_canvas.bind("<MouseWheel>", self.on_waveform_zoom)

        # ---- 右側腳本面板 ----
        script_panel = ctk.CTkFrame(paned, width=360, fg_color="#252525")
        paned.add(script_panel, minsize=180, width=360, stretch="never")
        script_panel.grid_propagate(False)
        script_panel.grid_columnconfigure(0, weight=1)
        script_panel.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            script_panel, text="腳本校稿",
            font=("Microsoft JhengHei UI", 14, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))

        script_tools = ctk.CTkFrame(script_panel, fg_color="transparent")
        script_tools.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        script_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_add_sentence = ctk.CTkButton(
            script_tools, text="＋ 新增", command=self.add_sentence_at_current_time, height=24, state="disabled"
        )
        self.btn_add_sentence.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=2)
        self.btn_split = ctk.CTkButton(
            script_tools, text="斷句", command=self.split_current_sentence, height=24, state="disabled"
        )
        self.btn_split.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=2)

        search_frame = ctk.CTkFrame(script_panel, fg_color="transparent")
        search_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        search_frame.grid_columnconfigure(0, weight=1)
        self._script_search_text = ctk.StringVar(value="")
        self._script_search_text.trace_add("write", lambda *_: self.refresh_script_panel())
        ctk.CTkEntry(
            search_frame, textvariable=self._script_search_text,
            placeholder_text="搜尋文字…", height=24,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._filter_speaker_var = ctk.StringVar(value="全部")
        self._filter_speaker_var.trace_add("write", lambda *_: self.refresh_script_panel())
        self._filter_speaker_combo = ctk.CTkComboBox(
            search_frame, variable=self._filter_speaker_var,
            values=["全部"], width=80, height=24, state="readonly",
        )
        self._filter_speaker_combo.grid(row=0, column=1, sticky="e")

        self.script_scroll = ctk.CTkScrollableFrame(script_panel)
        self.script_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 6))

        script_file_tools = ctk.CTkFrame(script_panel, fg_color="transparent")
        script_file_tools.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        script_file_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_load_data = ctk.CTkButton(
            script_file_tools, text="載入", command=self.load_data, height=24, state="disabled"
        )
        self.btn_load_data.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.btn_save_data = ctk.CTkButton(
            script_file_tools, text="儲存", command=self.save_data, height=24, state="disabled"
        )
        self.btn_save_data.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        self.refresh_script_panel()

        self.log("準備好了。先選影片，再框選要追蹤的人。")

    def show_shortcut_help(self, event=None):
        if hasattr(self, "_shortcut_win") and self._shortcut_win.winfo_exists():
            self._shortcut_win.lift()
            return
        win = ctk.CTkToplevel(self)
        win.title("快捷鍵一覽")
        win.geometry("520x380")
        win.transient(self)
        win.grab_set()
        self._shortcut_win = win
        shortcuts = [
            ("Space", "播放 / 暫停"),
            ("Enter", "播放目前句子"),
            ("Ctrl + Enter", "斷句（分割句子）"),
            ("↑ / ↓", "上 / 下一句"),
            ("← / →", "前 / 後一幀"),
            ("[ / ]", "微調開始 / 結束邊界 -0.05s"),
            ("Shift + [ / ]", "微調開始 / 結束邊界 +0.05s"),
            ("Ctrl + Z", "復原（Undo）"),
            ("Ctrl + Y", "重做（Redo）"),
            ("Delete", "刪除 / 還原句子"),
            ("Home / End", "跳至影片頭 / 尾"),
            ("? 或 /", "顯示此快捷鍵一覽"),
        ]
        frame = ctk.CTkFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        for i, (key, desc) in enumerate(shortcuts):
            ctk.CTkLabel(frame, text=key, font=("Consolas", 12, "bold"),
                         anchor="w", width=160).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=3)
            ctk.CTkLabel(frame, text=desc, anchor="w",
                         font=("Microsoft JhengHei UI", 12)).grid(row=i, column=1, sticky="w", pady=3)
        ctk.CTkButton(win, text="關閉", command=win.destroy, width=80).pack(pady=(0, 12))
        