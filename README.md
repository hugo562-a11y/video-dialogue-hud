<div align="center">

# 🎬 影片對話 HUD 工具
### Video Dialogue HUD

自動偵測影片中的人物，將對話字幕以氣泡形式疊加在說話者旁邊，匯出成品影片。

Automatically overlay speech-bubble dialogue on detected speakers and export the final video.

[![Platform](https://img.shields.io/badge/平台-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/授權-MIT-green)](LICENSE)
[![Tests](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml/badge.svg)](https://github.com/hugo562-a11y/video-dialogue-hud/actions/workflows/tests.yml)

[📥 立即下載 / Download](#-下載與安裝) · [功能介紹](#-功能) · [操作說明](#-操作說明) · [Developer Setup](#developer-setup-from-source)

</div>

---

<!-- TODO: 錄製操作示範 GIF 後取消下面的注釋
![Demo](docs/demo.gif)
-->

## 📥 下載與安裝

> 一般使用者請看這裡。**不需要安裝 Python，不需要任何程式知識。**

### 第一步：下載壓縮檔

前往 **[Releases 頁面](https://github.com/hugo562-a11y/video-dialogue-hud/releases/latest)**，下載最新版的：

```
VideoDialogueHUD_portable.zip
```

### 第二步：解壓縮

將 `.zip` 解壓縮到任意位置，例如：

```
D:\VideoDialogueHUD\
├── 影片對話HUD工具.exe   ← 主程式
├── ffmpeg.exe            ← 已內建，無需另外安裝
├── yolov8n.pt            ← AI 模型，已內建
└── （其他支援檔案）
```

### 第三步：直接執行

雙擊 `影片對話HUD工具.exe`，程式即可啟動。

> ⚠️ **第一次啟動** 需要約 10-30 秒載入 AI 模型，屬正常現象，請耐心等候。

> ⚠️ **Windows 安全警告**：若出現「Windows 已保護您的電腦」彈窗，點「更多資訊」→「仍要執行」即可。這是未購買程式碼簽章憑證的正常現象，程式本身無惡意程式碼。

---

## ✨ 功能

| 功能 | 說明 |
|---|---|
| **人物追蹤** | YOLOv8 自動偵測並追蹤畫面中的多位說話者 |
| **語音辨識** | 整合 Faster-Whisper，從影片音軌自動產生帶時間碼的對話腳本 |
| **對話氣泡** | 5 種樣式 × 6 種顏色 × 4 種位置，支援拖曳調整 |
| **波形編輯器** | 視覺化音軌波形，可手動對齊時間軸 |
| **對話編輯** | 分割、合併、刪除、還原、批次改名，附 Undo / Redo |
| **智慧匯出** | 自動剪除靜音段、ffmpeg 音訊合成、支援中文路徑 |
| **腳本匯入** | 支援 CSV / Excel（.xlsx / .xls）格式對話腳本 |

---

## 📖 操作說明

### 基本流程

```
1. 選取影片   →  載入 MP4 / AVI / MOV / MKV
2. 取得腳本   →  語音辨識（Whisper）或載入 CSV / Excel
3. 確認人數   →  設定影片中的說話者數量
4. 掃描人物   →  YOLO 逐幀追蹤每位說話者（需要幾分鐘）
5. 對應說話者 →  在右側面板將名稱對應到偵測人物
6. 調整樣式   →  設定每位說話者的氣泡顏色、樣式、位置
7. 匯出影片   →  渲染最終成品影片
```

### 對話腳本格式（CSV / Excel）

若要手動載入腳本，請準備以下欄位的表格：

| 欄位 | 格式 | 範例 |
|---|---|---|
| `start` | `HH:MM:SS`、`MM:SS` 或秒數 | `00:01:23` |
| `end` | 同上 | `00:01:27` |
| `speaker` | 說話者名稱 | `小明` |
| `text` | 對話內容 | `你好！` |

也支援單一 `time` 欄位格式：`"00:01:23 - 00:01:27"`

### 系統需求

- **作業系統**：Windows 10 / 11（64 位元）
- **顯示卡**：NVIDIA GPU 可大幅加速 AI 掃描（無 GPU 也能正常使用，但速度較慢）
- **硬碟空間**：程式本體約 1.5 GB

---

## 🔧 Developer Setup (from source)

> 以下內容供想要從原始碼執行或貢獻程式碼的開發者參考。

**系統需求：** Python 3.10+、ffmpeg（加入 PATH）、Git

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
python main.py
```

> **GPU 使用者**：請先至 [pytorch.org](https://pytorch.org/get-started/locally/) 安裝對應 CUDA 版本的 PyTorch，再執行上述指令。

### 建置可攜式 EXE

```bash
# 雙擊執行即可（自動下載所有必要資源並打包）
build_portable.bat
```

建置完成後會產出 `VideoDialogueHUD_portable.zip`，上傳至 GitHub Releases 供使用者下載。

### 執行測試

```bash
python -m pytest tests/ -v
```

### 專案結構

```
video-dialogue-hud/
├── main.py                 # 程式入口
├── requirements.txt        # Python 套件清單
├── main.spec               # PyInstaller 打包設定
├── build_portable.bat      # 一鍵建置腳本
├── core/
│   ├── constants.py        # 全域常數與路徑
│   ├── data_processor.py   # 對話資料管理
│   ├── utils.py            # 時間解析、格式轉換
│   └── video_renderer.py   # YOLO 追蹤、氣泡渲染、影片匯出
├── ui/
│   ├── app.py              # 主視窗
│   ├── controls.py         # 播放、Undo/Redo
│   ├── editing.py          # 句子編輯操作
│   ├── preview.py          # 預覽畫布（縮放、平移）
│   ├── script_panel.py     # 右側對話腳本面板
│   ├── waveform.py         # 音訊波形顯示
│   └── workflow.py         # 載入→掃描→匯出流程
└── tests/
    └── test_core_logic.py
```

---

## 🤝 Contributing

歡迎提交 Issue 或 Pull Request！請先閱讀 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 📄 授權 / License

[MIT](LICENSE) © 2026
