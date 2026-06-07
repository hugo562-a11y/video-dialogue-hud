<div align="center">

# 🎬 Video Dialogue HUD

**影片對話 HUD 工具**

Automatically detect speakers in a video, overlay their dialogue as styled speech bubbles, and export the final cut — all from a single desktop app.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml/badge.svg)](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml)

[English](#overview) · [中文說明](#中文說明)

</div>

---

## Overview

**Video Dialogue HUD** is a desktop tool for content creators and video editors who work with multi-speaker footage. It tracks each person using YOLOv8, maps their lines from a dialogue script (CSV / Excel) or auto-transcribes audio via Faster-Whisper, and renders customisable speech-bubble overlays directly onto the video.

<!-- TODO: add a demo GIF here — recommended size 1200×675 -->
<!-- ![Demo](docs/demo.gif) -->

### Key Features

| Feature | Details |
|---|---|
| **Person tracking** | YOLOv8 Nano — detects & tracks multiple people across frames |
| **Auto-transcription** | Faster-Whisper integration; generates a time-coded dialogue script from audio |
| **Speech bubbles** | 5 styles (classic / oval / capsule / tech / sharp), 6 colours, 4 positions, drag-to-reposition |
| **Waveform editor** | Visual audio waveform with interactive time-range editing |
| **Dialogue editor** | Split, merge, delete, restore, bulk speaker rename, undo / redo |
| **Smart export** | Cuts silence segments, merges audio with ffmpeg, handles CJK paths safely |
| **Script import** | Load dialogue from CSV or Excel (`.xlsx` / `.xls`) |

---

## Requirements

- **OS**: Windows 10 / 11 (64-bit)
- **Python**: 3.10 or newer
- **ffmpeg**: must be on `PATH` or placed in the project root → [download](https://ffmpeg.org/download.html)
- **GPU** *(optional)*: NVIDIA GPU with CUDA improves YOLO scanning and Whisper transcription speed significantly

---

## Installation

### 1 — Clone the repository

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud
```

### 2 — Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
```

> **GPU users**: install a CUDA-enabled PyTorch build *before* running the command above.
> Visit [pytorch.org/get-started](https://pytorch.org/get-started/locally/) and select your CUDA version.

### 4 — Download the YOLOv8 model

The model file is not bundled in the repository. Download it once:

```bash
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

This saves `yolov8n.pt` into the Ultralytics cache; the app will find it automatically.
Alternatively, download it manually from [ultralytics/assets](https://github.com/ultralytics/assets/releases) and place it in the project root.

### 5 — CJK font *(optional)*

The app falls back to Windows' built-in `msjh.ttc` (MingLiU). For sharper CJK rendering in exported videos, download **Noto Sans CJK TC Bold** from [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+TC) and place `NotoSansCJKtc-Bold.otf` in the project root.

---

## Usage

```bash
python main.py
```

### Workflow

```
1. Select video     →  load MP4 / AVI / MOV / MKV
2. Load script      →  auto-transcribe (Whisper) or import CSV / Excel
3. Confirm people   →  set the number of speakers in the video
4. Scan             →  YOLO tracks each person frame-by-frame
5. Map speakers     →  assign speaker names to detected persons
6. Customise style  →  choose bubble style, colour, and position per speaker
7. Export           →  render final video with overlaid bubbles
```

### Dialogue script format

The app accepts a CSV or Excel file with these columns:

| Column | Format | Example |
|---|---|---|
| `start` | `HH:MM:SS`, `MM:SS`, or seconds | `00:01:23` |
| `end` | same as `start` | `00:01:27` |
| `speaker` | any string | `Alice` |
| `text` | dialogue line | `Hello there!` |

Columns named `time` (as `"HH:MM:SS - HH:MM:SS"`) are also supported.

---

## Running Tests

```bash
python -m pytest tests/ -v
# or
python -m unittest discover tests/
```

---

## Project Structure

```
video-dialogue-hud/
├── main.py                 # Entry point
├── requirements.txt
├── main.spec               # PyInstaller spec (standalone EXE build)
├── build_portable.bat      # Build helper script
├── core/
│   ├── constants.py        # Global constants, paths
│   ├── data_processor.py   # Dialogue DataFrame management
│   ├── utils.py            # Time parsing, formatting helpers
│   └── video_renderer.py   # YOLO tracking, bubble rendering, export
├── ui/
│   ├── app.py              # Main window (mixin orchestration)
│   ├── controls.py         # Playback, undo/redo, logging
│   ├── editing.py          # Sentence split / merge / delete
│   ├── preview.py          # Canvas with zoom, pan, ROI
│   ├── script_panel.py     # Right-panel dialogue editor
│   ├── waveform.py         # Audio waveform visualisation
│   └── workflow.py         # Load → scan → export pipeline
└── tests/
    └── test_core_logic.py
```

---

## Building a Standalone EXE

Requires [PyInstaller](https://pyinstaller.org/):

```bash
pip install pyinstaller
pyinstaller main.spec
```

The output appears in `dist/影片對話HUD工具/`. You can also run `build_portable.bat` which handles the full build in one step.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

---

## License

[MIT](LICENSE) © 2026

---

## 中文說明

### 簡介

**影片對話 HUD 工具** 是一款 Windows 桌面應用程式，能自動偵測影片中的說話者，並將對話字幕以氣泡樣式疊加在對應人物旁邊，最後匯出成品影片。

### 主要功能

- **YOLOv8 人物追蹤**：自動偵測並追蹤多位說話者
- **語音辨識**：整合 Faster-Whisper，從影片音軌自動生成帶時間碼的對話腳本
- **對話氣泡**：5 種樣式、6 種顏色、4 種位置，支援拖曳調整位置
- **波形編輯器**：視覺化音軌，可手動對齊時間軸
- **對話編輯**：分割、合併、刪除、還原、批次改名說話者，附完整 Undo / Redo
- **智慧匯出**：自動剪除靜音段、ffmpeg 音訊合成、支援中文路徑

### 快速開始

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

詳細安裝步驟請見 [Installation](#installation)。

### 基本操作流程

1. **選取影片** → 載入 MP4 / AVI / MOV / MKV
2. **取得腳本** → 語音辨識（Whisper）或載入 CSV / Excel 腳本
3. **確認人數** → 設定影片中的說話者數量
4. **掃描人物** → YOLO 逐幀追蹤每位說話者
5. **對應說話者** → 在腳本面板中將名稱對應到偵測人物
6. **調整樣式** → 設定氣泡顏色、樣式、位置
7. **匯出影片** → 渲染最終成品
