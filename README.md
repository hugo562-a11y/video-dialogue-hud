<div align="center">

# 🎬 影片對話 HUD 工具 · Video Dialogue HUD

自動追蹤影片人物，將對話字幕以氣泡樣式疊加在說話者旁邊，匯出成品影片。

Automatically track speakers in a video, overlay dialogue as speech bubbles, and export the final cut.

[![Platform](https://img.shields.io/badge/Windows-10%2F11%2064bit-0078D6?logo=windows)](https://www.microsoft.com/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-brightgreen)](LICENSE)
[![Tests](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml/badge.svg)](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml)

</div>

<!-- TODO: 錄製示範 GIF 後取消注釋 / Uncomment after recording a demo GIF
![Demo](docs/demo.gif)
-->

---

## ✨ 功能 · Features

| 功能 · Feature | 說明 · Details |
|---|---|
| **人物追蹤 · Person tracking** | YOLOv8 Nano 自動偵測並追蹤多位說話者；有 NVIDIA GPU 時自動啟用 GPU 加速，無 GPU 則自動退回 CPU 執行 · Auto-detects and tracks multiple speakers; uses GPU when available, falls back to CPU automatically |
| **語音辨識 · Auto-transcription** | Faster-Whisper 從音軌產生帶時間碼的對話腳本 · Generates time-coded script from audio |
| **對話氣泡 · Speech bubbles** | 5 種樣式 × 6 種顏色 × 4 種位置，支援拖曳調整 · 5 styles × 6 colours × 4 positions |
| **波形編輯器 · Waveform editor** | 視覺化音軌，可手動對齊時間軸 · Visual waveform with interactive time editing |
| **對話編輯 · Dialogue editor** | 分割、合併、刪除、還原、批次改名，附 Undo / Redo |
| **智慧匯出 · Smart export** | 自動剪除靜音段、ffmpeg 音訊合成 · Silence cutting, ffmpeg audio merge |
| **腳本匯入 · Script import** | 支援 CSV / Excel（.xlsx / .xls）· Supports CSV and Excel |

---

## 🚀 安裝與執行 · Installation

### 系統需求 · Requirements

| 項目 | 說明 |
|---|---|
| 作業系統 · OS | Windows 10 / 11（64 位元 · 64-bit） |
| Python | 3.10 或以上 · 3.10 or newer → [python.org](https://www.python.org/downloads/) |
| ffmpeg | 需加入系統 PATH · Must be on system PATH → [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) 下載 `ffmpeg-release-essentials.zip` |
| 顯示卡 · GPU | 非必要。有 NVIDIA GPU 時自動啟用 CUDA 加速；無 GPU 則自動改用 CPU，掃描速度較慢但功能完整 · Optional. NVIDIA GPU enables CUDA acceleration automatically; without one the app falls back to CPU — slower but fully functional |

### 安裝步驟 · Steps

**1. 複製專案 · Clone**

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud
```

**2. 建立虛擬環境 · Create virtual environment**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**3. 安裝套件 · Install dependencies**

```bash
pip install -r requirements.txt
```

> **GPU 使用者 · GPU users：** 請先至 [pytorch.org/get-started](https://pytorch.org/get-started/locally/) 安裝對應 CUDA 版本的 PyTorch，再執行上方指令。
>
> Install a CUDA-enabled PyTorch build **before** running the above command.

**4. 啟動程式 · Launch**

```bash
python main.py
```

---

## 📖 操作說明 · How to Use

### 操作流程 · Workflow

```
步驟 · Step    中文                    English
─────────────────────────────────────────────────────────
1              選取影片                Select video  (MP4 / AVI / MOV / MKV)
2              取得腳本                Load script — transcribe or import CSV / Excel
3              確認說話者人數           Set number of speakers
4              掃描人物（需幾分鐘）     Scan — YOLO tracks each person frame-by-frame
5              對應說話者名稱           Map speaker names to detected persons
6              調整氣泡樣式             Customise bubble style, colour, position
7              匯出影片                Export final video
```

### 對話腳本格式 · Dialogue Script Format

手動載入 CSV / Excel 腳本時，表格需包含以下欄位：

When importing manually, the file should contain these columns:

| 欄位 · Column | 格式 · Format | 範例 · Example |
|---|---|---|
| `start` | `HH:MM:SS`、`MM:SS` 或秒數 · or seconds | `00:01:23` |
| `end` | 同上 · same | `00:01:27` |
| `speaker` | 說話者名稱 · Speaker name | `小明 / Alice` |
| `text` | 對話內容 · Dialogue line | `你好！/ Hello!` |

也支援單欄 `time` 格式：`"00:01:23 - 00:01:27"`
Single-column `time` format is also supported.

---

## 🔧 進階 · Advanced

### 建置獨立 EXE · Build standalone EXE

```bash
# 自動下載所有必要資源並以 PyInstaller 打包
# Auto-downloads required assets and builds with PyInstaller
build_portable.bat
```

輸出位於 `dist\影片對話HUD工具\`。
Output is in `dist\影片對話HUD工具\`. Copy `ffmpeg.exe` into that folder before distributing.

### 執行測試 · Run tests

```bash
python -m pytest tests/ -v
```

### 專案結構 · Project structure

```
video-dialogue-hud/
├── main.py                 # 程式入口 · Entry point
├── requirements.txt
├── main.spec               # PyInstaller 打包設定 · Build spec
├── build_portable.bat      # 一鍵建置腳本 · One-click build script
├── core/
│   ├── constants.py        # 全域常數與路徑 · Global constants
│   ├── data_processor.py   # 對話資料管理 · Dialogue data management
│   ├── utils.py            # 時間解析等工具 · Time parsing utilities
│   └── video_renderer.py   # YOLO 追蹤、氣泡渲染、匯出 · YOLO, bubbles, export
├── ui/
│   ├── app.py              # 主視窗 · Main window
│   ├── controls.py         # 播放、Undo/Redo · Playback, undo/redo
│   ├── editing.py          # 句子編輯 · Sentence editing
│   ├── preview.py          # 預覽畫布 · Preview canvas
│   ├── script_panel.py     # 對話腳本面板 · Script panel
│   ├── waveform.py         # 音訊波形 · Audio waveform
│   └── workflow.py         # 載入→掃描→匯出 · Load→scan→export
└── tests/
    └── test_core_logic.py
```

---

## 🤝 Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

---

## 📄 授權 · License

[MIT](LICENSE) © 2026
