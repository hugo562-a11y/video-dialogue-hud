"""App — 主視窗，繼承所有 Mixin 並建構 UI。"""
from __future__ import annotations

import queue
import tkinter as tk

import customtkinter as ctk

from core.constants import APP_TITLE, MIN_SILENCE_SECONDS
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
        ctk.set_default_color_theme("blue")
        self.configure(fg_color="#060B14")

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
        self.bind_all("<Return>", self.play_current_sentence)
        self.bind_all("<Delete>", self.delete_selected_dialogue)
        self.bind_all("<bracketleft>", lambda e: self.nudge_dialogue_edge("start", -0.05, e))
        self.bind_all("<bracketright>", lambda e: self.nudge_dialogue_edge("end", 0.05, e))
        self.bind_all("<Shift-bracketleft>", lambda e: self.nudge_dialogue_edge("start", 0.05, e))
        self.bind_all("<Shift-bracketright>", lambda e: self.nudge_dialogue_edge("end", -0.05, e))
        self.check_queue()

    def setup_ui(self):
        self.script_row_widgets = {}
        self._script_row_loading = False
        self._log_expanded = True

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # ---- 左側邊欄 ----
        sidebar = ctk.CTkFrame(self, width=240, fg_color="#111827", corner_radius=8)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(17, weight=1)

        ctk.CTkLabel(sidebar, text="影片對話 HUD", font=("Microsoft JhengHei UI", 20, "bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 2)
        )
        ctk.CTkLabel(sidebar, text="校稿工作台", text_color="#AAB0C0", anchor="w").grid(
            row=1, column=0, sticky="ew", padx=14, pady=(0, 12)
        )

        self.btn_video = ctk.CTkButton(sidebar, text="1  選擇影片", command=self.select_video, height=34)
        self.workflow_group_labels = {}
        self.workflow_group_labels["import"] = ctk.CTkLabel(
            sidebar, text="1. 匯入與代理檔", anchor="w",
            font=("Microsoft JhengHei UI", 13, "bold"), text_color="#43E2A8",
        )
        self.workflow_group_labels["import"].grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 2))
        self.btn_video.configure(text="選擇影片")
        self.btn_video.grid(row=3, column=0, sticky="ew", padx=12, pady=4)

        # 人物工具（確認 / 清除）
        person_tools = ctk.CTkFrame(sidebar, fg_color="transparent")
        self.workflow_group_labels["people"] = ctk.CTkLabel(
            sidebar, text="3. 人物與掃描", anchor="w",
            font=("Microsoft JhengHei UI", 13, "bold"), text_color="#AAB0C0",
        )
        self.workflow_group_labels["people"].grid(row=7, column=0, sticky="ew", padx=12, pady=(10, 2))
        person_tools.grid(row=10, column=0, sticky="ew", padx=12, pady=(0, 4))
        person_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_confirm_people = ctk.CTkButton(
            person_tools, text="4  確認", command=self.confirm_people_count, height=30, state="disabled"
        )
        self.btn_confirm_people.configure(text="確認框選")
        self.btn_confirm_people.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_clear_people = ctk.CTkButton(
            person_tools, text="清除", command=self.clear_person_boxes, height=30,
            state="disabled", fg_color="#6B7280", hover_color="#7B8494",
        )
        self.btn_clear_people.configure(text="清除")
        self.btn_clear_people.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.btn_speech = ctk.CTkButton(
            sidebar, text="2  辨識聲音", command=self.generate_speech_script,
            height=34, state="disabled", fg_color="#B94A48", hover_color="#D15A57",
        )
        self.workflow_group_labels["speech"] = ctk.CTkLabel(
            sidebar, text="2. 聲音與腳本", anchor="w",
            font=("Microsoft JhengHei UI", 13, "bold"), text_color="#AAB0C0",
        )
        self.workflow_group_labels["speech"].grid(row=4, column=0, sticky="ew", padx=12, pady=(10, 2))
        self.btn_speech.configure(text="辨識聲音")
        self.btn_speech.grid(row=5, column=0, sticky="ew", padx=12, pady=4)

        self.btn_name_people = ctk.CTkButton(
            sidebar, text="3  人物命名", command=self.open_person_namer,
            height=34, state="disabled", fg_color="#2563EB", hover_color="#1D4ED8",
        )
        self.btn_name_people.configure(text="命名人物")
        self.btn_name_people.grid(row=8, column=0, sticky="ew", padx=12, pady=4)

        self.btn_draw_people = ctk.CTkButton(
            sidebar, text="4  框選追踪", command=self.start_person_box_mode, height=34, state="disabled"
        )
        self.btn_draw_people.configure(text="框選人物")
        self.btn_draw_people.grid(row=9, column=0, sticky="ew", padx=12, pady=4)

        self.btn_scan = ctk.CTkButton(
            sidebar, text="5  掃描人物", command=self.start_preview_scan,
            height=34, state="disabled"
        )
        self.btn_scan.configure(text="掃描人物")
        self.btn_scan.grid(row=11, column=0, sticky="ew", padx=12, pady=4)

        self.btn_export = ctk.CTkButton(
            sidebar, text="6  匯出影片", command=self.start_export,
            height=34, state="disabled", fg_color="#2E8B57", hover_color="#35A568",
        )
        self.workflow_group_labels["export"] = ctk.CTkLabel(
            sidebar, text="4. 校稿與匯出", anchor="w",
            font=("Microsoft JhengHei UI", 13, "bold"), text_color="#AAB0C0",
        )
        self.workflow_group_labels["export"].grid(row=12, column=0, sticky="ew", padx=12, pady=(10, 2))
        self.btn_export.configure(text="匯出影片")
        self.btn_export_preview = ctk.CTkButton(
            sidebar, text="匯出預覽影片", command=self.start_preview_export,
            height=32, state="disabled", fg_color="#4B5563", hover_color="#5B6473",
        )
        self.btn_export_preview.grid(row=13, column=0, sticky="ew", padx=12, pady=(4, 2))
        self.btn_export.grid(row=14, column=0, sticky="ew", padx=12, pady=4)

        self.progress_bar = ctk.CTkProgressBar(sidebar)
        self.progress_bar.grid(row=15, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(
            sidebar, text="尚未選擇影片", anchor="w", justify="left", wraplength=190
        )
        self.status_label.configure(text="先選擇影片，工具會建立 720 proxy。", wraplength=210)
        self.status_label.grid(row=16, column=0, sticky="ew", padx=12, pady=(0, 8))

        self.btn_open_export = ctk.CTkButton(
            sidebar, text="開啟輸出影片", command=self.open_export_video,
            height=30, state="disabled", fg_color="#2563EB", hover_color="#1D4ED8",
        )
        self.btn_open_export.configure(text="開啟輸出影片")
        self.btn_open_export.grid(row=17, column=0, sticky="ew", padx=12, pady=(4, 4))

        self.btn_toggle_log = ctk.CTkButton(
            sidebar, text="隱藏記錄", command=self.toggle_log_panel,
            height=30, fg_color="#4B5563", hover_color="#5B6473",
        )
        self.btn_toggle_log.configure(text="顯示/隱藏記錄")
        self.btn_toggle_log.grid(row=19, column=0, sticky="ew", padx=12, pady=(2, 4))
        self.log_box = ctk.CTkTextbox(sidebar, wrap="word", height=160)
        self.log_box.grid(row=18, column=0, sticky="nsew", padx=12, pady=(4, 12))

        # ---- 中央主區域 ----
        main = ctk.CTkFrame(self, fg_color="#0B1220", corner_radius=8)
        main.grid(row=0, column=1, sticky="nsew", padx=6, pady=10)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(2, weight=0)

        # 頂部設定列（隱藏 entry_id/speaker/text，僅保留現在句顯示 + 設定）
        controls = ctk.CTkFrame(main, fg_color="#111827", corner_radius=8)
        controls.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        controls.grid_columnconfigure(7, weight=1)

        # 邏輯用欄位，不放在格局中（不可見，但仍持有資料）
        self.entry_id = ctk.CTkEntry(controls, width=1)
        self.entry_id.insert(0, "1")
        self.entry_speaker = ctk.CTkEntry(controls, width=1)
        self.entry_text = ctk.CTkEntry(controls, width=1)

        ctk.CTkLabel(controls, text="辨識", anchor="w").grid(row=0, column=0, padx=(10, 4), pady=(8, 2), sticky="w")
        self.whisper_model_var = ctk.StringVar(value="medium")
        self.whisper_menu = ctk.CTkOptionMenu(
            controls, values=["base", "small", "medium", "large-v3"],
            variable=self.whisper_model_var, width=118, height=30, state="disabled",
        )
        self.whisper_menu.grid(row=0, column=1, padx=(0, 12), pady=(8, 2), sticky="w")

        ctk.CTkLabel(controls, text="字級", anchor="w").grid(row=0, column=2, padx=(0, 4), pady=(8, 2), sticky="w")
        self.slider_font_size = ctk.CTkSlider(controls, from_=18, to=180, width=140, command=self.update_style)
        self.slider_font_size.set(72)
        self.slider_font_size.grid(row=0, column=3, padx=(0, 12), pady=(8, 2), sticky="w")

        ctk.CTkLabel(controls, text="無講話", anchor="w").grid(row=0, column=4, padx=(0, 4), pady=(8, 2), sticky="w")
        self.silence_slider = ctk.CTkSlider(
            controls, from_=0.2, to=1.5, number_of_steps=13, width=130, variable=self.silence_seconds_var
        )
        self.silence_slider.grid(row=0, column=5, padx=(0, 4), pady=(8, 2), sticky="w")
        self.lbl_silence = ctk.CTkLabel(controls, text="0.45s", width=52)
        self.lbl_silence.grid(row=0, column=6, padx=(0, 12), pady=(8, 2), sticky="w")
        self.silence_slider.configure(command=lambda v: self.lbl_silence.configure(text=f"{float(v):.2f}s"))

        self.audio_scrub_check = ctk.CTkCheckBox(
            controls, text="聲波定位", variable=self.audio_scrub_var, width=96
        )
        self.audio_scrub_check.grid(row=0, column=7, padx=(0, 8), pady=(8, 2), sticky="w")

        self.current_sentence_label = ctk.CTkLabel(
            controls, text="在右側腳本列表修改文字與說話者",
            anchor="w", text_color="#AAB0C0",
        )
        self.current_sentence_label.grid(row=1, column=0, columnspan=8, padx=(10, 8), pady=(0, 8), sticky="ew")

        self.btn_undo = ctk.CTkButton(controls, text="Undo", width=62, command=self.undo_action)
        self.btn_undo.grid(row=0, column=8, padx=(10, 4), pady=(8, 2))
        self.btn_redo = ctk.CTkButton(controls, text="Redo", width=62, command=self.redo_action)
        self.btn_redo.grid(row=0, column=9, padx=(4, 10), pady=(8, 2))

        # 預覽畫布
        canvas_frame = ctk.CTkFrame(main, fg_color="#070A10")
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.preview_canvas = tk.Canvas(
            canvas_frame, bg="#070A10", highlightthickness=0, cursor="crosshair", takefocus=1
        )
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.create_text(420, 240, text="選擇影片後會顯示預覽", fill="#687084", font=("Microsoft JhengHei UI", 16))
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_scroll)
        self.preview_canvas.bind("<ButtonPress-1>", self._on_canvas_drag_start)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.preview_canvas.bind("<ButtonPress-3>", self._on_canvas_right_click)
        self.preview_canvas.bind("<Motion>", self._on_canvas_motion)

        # 時間軸列
        tool_row = ctk.CTkFrame(main, fg_color="#111827", corner_radius=8)
        tool_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        tool_row.grid_columnconfigure(1, weight=1)

        self.lbl_timecode = ctk.CTkLabel(
            tool_row, text="00:00", width=70, font=("Consolas", 15, "bold"), text_color="#43E2A8"
        )
        self.lbl_timecode.grid(row=0, column=0, sticky="w", padx=(8, 8), pady=(8, 4))
        self.slider_timeline = ctk.CTkSlider(tool_row, from_=1, to=1, command=self.on_timeline_scrub, state="disabled")

        self.waveform_canvas = tk.Canvas(tool_row, height=128, bg="#111827", highlightthickness=0)
        self.waveform_canvas.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 8))
        self.waveform_canvas.bind("<Button-1>", self.on_waveform_click)
        self.waveform_canvas.bind("<B1-Motion>", self.on_waveform_drag)
        self.waveform_canvas.bind("<ButtonRelease-1>", self.on_waveform_release)
        self.waveform_canvas.bind("<Button-3>", self.on_waveform_pan_start)
        self.waveform_canvas.bind("<B3-Motion>", self.on_waveform_pan_drag)
        self.waveform_canvas.bind("<ButtonRelease-3>", self.on_waveform_pan_release)
        self.waveform_canvas.bind("<Motion>", self.on_waveform_motion)
        self.waveform_canvas.bind("<MouseWheel>", self.on_waveform_zoom)

        # ---- 右側腳本面板 ----
        script_panel = ctk.CTkFrame(self, width=390, fg_color="#111827", corner_radius=8)
        script_panel.grid(row=0, column=2, sticky="nsew", padx=(6, 10), pady=10)
        script_panel.grid_propagate(False)
        script_panel.grid_columnconfigure(0, weight=1)
        script_panel.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            script_panel, text="腳本校稿",
            font=("Microsoft JhengHei UI", 18, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        script_tools = ctk.CTkFrame(script_panel, fg_color="transparent")
        script_tools.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        script_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_add_sentence = ctk.CTkButton(
            script_tools, text="新增", command=self.add_sentence_at_current_time, height=30, state="disabled"
        )
        self.btn_add_sentence.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=3)
        self.btn_split = ctk.CTkButton(
            script_tools, text="斷句", command=self.split_current_sentence, height=30, state="disabled"
        )
        self.btn_split.grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=3)

        self.script_scroll = ctk.CTkScrollableFrame(script_panel)
        self.script_scroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))

        script_file_tools = ctk.CTkFrame(script_panel, fg_color="transparent")
        script_file_tools.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        script_file_tools.grid_columnconfigure((0, 1), weight=1)
        self.btn_load_data = ctk.CTkButton(
            script_file_tools, text="載入腳本", command=self.load_data, height=32, state="disabled"
        )
        self.btn_load_data.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_save_data = ctk.CTkButton(
            script_file_tools, text="儲存腳本", command=self.save_data, height=32, state="disabled"
        )
        self.btn_save_data.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.refresh_script_panel()

        self.log("準備好了。先選影片，再框選要追蹤的人。")
