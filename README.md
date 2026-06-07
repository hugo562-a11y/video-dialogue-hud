<div align="center">

# 🎬 影片對話 HUD 工具 · Video Dialogue HUD

自動追蹤影片人物，將對話字幕以氣泡樣式疊加在說話者旁邊，匯出成品影片。

Automatically track speakers in a video, overlay dialogue as speech bubbles, and export the final cut.

[![Platform](https://img.shields.io/badge/Windows-10%2F11%2064bit-0078D6?logo=windows)](https://www.microsoft.com/)
[![License](https://img.shields.io/badge/License-MIT-brightgreen)](LICENSE)
[![Tests](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml/badge.svg)](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml)

</div>

<!-- TODO: 錄製示範 GIF 後取消注釋
![Demo](docs/demo.gif)
-->

---

## 📥 下載與安裝 · Download & Install

> **中文使用者** — 請看這裡。不需要安裝 Python，不需要任何程式知識。
>
> **English users** — Start here. No Python installation required.

---

### 步驟一 · Step 1 — 下載程式 · Download the app

前往 **[Releases 頁面](https://github.com/hugo562-a11y/video-dialogue-hud/releases/latest)** 下載最新版：

Go to the **[Releases page](https://github.com/hugo562-a11y/video-dialogue-hud/releases/latest)** and download:

```
VideoDialogueHUD_portable.zip
```

---

### 步驟二 · Step 2 — 下載 ffmpeg · Download ffmpeg

本程式**不內建 ffmpeg**，需要您自行下載（免費、開源）。

ffmpeg is **not bundled** with the app. You need to download it separately (free & open source).

1. 前往 · Go to: **https://www.gyan.dev/ffmpeg/builds/**
2. 下載 · Download: **`ffmpeg-release-essentials.zip`**（頁面中間的下載連結）
3. 解壓縮，找到 `bin` 資料夾裡的 **`ffmpeg.exe`**
4. 把 **`ffmpeg.exe`** 複製到程式資料夾（和 `影片對話HUD工具.exe` 放在一起）

   Extract the zip → open the `bin` folder → copy **`ffmpeg.exe`** into the app folder (same folder as `影片對話HUD工具.exe`).

完成後的資料夾結構 · Folder structure after setup:

```
VideoDialogueHUD\
├── 影片對話HUD工具.exe   ← 主程式 · Main app
├── ffmpeg.exe            ← 自行下載放入 · You add this
├── yolov8n.pt            ← AI 模型，已內建 · Bundled
└── （其他支援檔案 · other support files）
```

---

### 步驟三 · Step 3 — 解壓縮並執行 · Extract and run

1. 將 `VideoDialogueHUD_portable.zip` 解壓縮到任意位置

   Extract `VideoDialogueHUD_portable.zip` anywhere you like.

2. 把 `ffmpeg.exe` 放進解壓縮後的資料夾

   Copy `ffmpeg.exe` into the extracted folder.

3. 雙擊 `影片對話HUD工具.exe` 即可啟動

   Double-click `影片對話HUD工具.exe` to launch.

> ⚠️ **第一次啟動較慢 · First launch is slow**
> 首次開啟需要約 10–30 秒載入 AI 模型，屬正常現象，請耐心等候。
> The first launch takes 10–30 seconds to load the AI model — this is normal.

> ⚠️ **Windows 安全警告 · Windows security warning**
> 若出現「Windows 已保護您的電腦」，點「更多資訊」→「仍要執行」。
> If you see "Windows protected your PC", click "More info" → "Run anyway".

---

## ✨ 功能 · Features

| 功能 · Feature | 說明 · Details |
|---|---|
| **人物追蹤 · Person tracking** | YOLOv8 Nano 自動偵測並追蹤多位說話者 |
| **語音辨識 · Auto-transcription** | Faster-Whisper 從影片音軌自動產生對話腳本 |
| **對話氣泡 · Speech bubbles** | 5 種樣式 × 6 種顏色 × 4 種位置，支援拖曳調整 |
| **波形編輯器 · Waveform editor** | 視覺化音軌，可手動對齊時間軸 |
| **對話編輯 · Dialogue editor** | 分割、合併、刪除、還原、批次改名，附 Undo / Redo |
| **智慧匯出 · Smart export** | 自動剪除靜音段、ffmpeg 音訊合成、支援中文路徑 |
| **腳本匯入 · Script import** | 支援 CSV / Excel（.xlsx / .xls）格式 |

---

## 📖 操作說明 · How to Use

### 操作流程 · Workflow

```
中文                              English
──────────────────────────────────────────────────────────
1. 選取影片                       Select video (MP4/AVI/MOV/MKV)
2. 取得腳本                       Load script — transcribe or import CSV/Excel
3. 確認說話者人數                  Set number of speakers
4. 掃描人物（需幾分鐘）            Scan — YOLO tracks each person (takes a few minutes)
5. 對應說話者名稱                  Map speaker names to detected persons
6. 調整氣泡樣式                   Customise bubble style, colour, position
7. 匯出影片                       Export final video
```

### 對話腳本格式 · Dialogue Script Format

手動載入 CSV / Excel 腳本時，欄位如下：

When importing a CSV or Excel script manually, use these columns:

| 欄位 · Column | 格式 · Format | 範例 · Example |
|---|---|---|
| `start` | `HH:MM:SS`、`MM:SS` 或秒數 / or seconds | `00:01:23` |
| `end` | 同上 · same | `00:01:27` |
| `speaker` | 說話者名稱 · Speaker name | `小明 / Alice` |
| `text` | 對話內容 · Dialogue | `你好！/ Hello!` |

也支援單欄 `time` 格式：`"00:01:23 - 00:01:27"`

Single-column `time` format is also supported: `"00:01:23 - 00:01:27"`

---

## 🔧 Developer Setup

> For contributors who want to run from source.

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**GPU support:** Install a CUDA-enabled PyTorch build first → [pytorch.org/get-started](https://pytorch.org/get-started/locally/)

### Build portable EXE

```bash
build_portable.bat   # auto-downloads assets and creates VideoDialogueHUD_portable.zip
```

### Run tests

```bash
python -m pytest tests/ -v
```

---

## 🤝 Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

---

## 📄 License · 授權

[MIT](LICENSE) © 2026
