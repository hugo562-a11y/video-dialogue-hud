# 影片對話 HUD 工具

自動偵測影片中的人物，將對話字幕以氣泡形式疊加在對應人物旁邊，並匯出成品影片。

![平台](https://img.shields.io/badge/平台-Windows-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-green)
![授權](https://img.shields.io/badge/授權-MIT-yellow)

---

## 功能

- **人物追蹤**：使用 YOLOv8 自動偵測並追蹤畫面中的人物
- **對話氣泡**：將 CSV / Excel 對話腳本對應到各人物，以氣泡疊加顯示
- **語音辨識**：整合 faster-whisper，可自動從影片音軌產生對話腳本
- **氣泡樣式**：6 種樣式（classic / oval / capsule / tech / sharp）、6 種顏色、4 種位置
- **波形編輯**：視覺化音軌波形，可手動對齊時間軸
- **剪輯輸出**：支援標記靜音段落並剪除，匯出最終影片

---

## 系統需求

- Windows 10 / 11（64 位元）
- Python 3.10 或以上
- [ffmpeg](https://ffmpeg.org/download.html)（需加入系統 PATH）

> GPU 加速（NVIDIA CUDA）非必要，但有 GPU 時處理速度明顯較快。

---

## 安裝步驟

**1. 複製專案**

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud
```

**2. 建立虛擬環境（建議）**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**3. 安裝依賴套件**

```bash
pip install -r requirements.txt
```

**4. 安裝 ffmpeg**

至 [ffmpeg.org](https://ffmpeg.org/download.html) 下載 Windows 版本，將 `ffmpeg.exe` 加入系統 PATH，或放在專案根目錄。

**5. 字型（可選）**

程式預設使用 Windows 內建的微軟正黑體（`msjh.ttc`）。若需要更完整的 CJK 字型，可下載 [Noto Sans CJK TC Bold](https://fonts.google.com/noto/specimen/Noto+Sans+TC) 並將 `NotoSansCJKtc-Bold.otf` 放在專案根目錄。

---

## 使用方式

```bash
python main.py
```

### 基本流程

1. **選取影片**：點擊「選取影片」載入 MP4 / AVI / MOV / MKV
2. **取得對話腳本**：
   - 自動辨識：點擊「語音辨識」由 Whisper 自動產生（需先安裝 faster-whisper）
   - 手動載入：點擊「載入腳本」選取 CSV 或 Excel 檔
3. **掃描人物**：點擊「掃描人物」讓 YOLO 追蹤畫面中的人物
4. **對應說話者**：在腳本面板中將說話者名稱對應到偵測到的人物
5. **調整樣式**：設定氣泡顏色、樣式、位置
6. **匯出影片**：點擊「匯出」產生成品

### 對話腳本格式（CSV / Excel）

| 欄位 | 說明 |
|------|------|
| `start` | 開始時間（格式：`HH:MM:SS` 或秒數） |
| `end` | 結束時間 |
| `speaker` | 說話者名稱 |
| `text` | 對話內容 |

---

## 依賴套件

| 套件 | 用途 |
|------|------|
| customtkinter | 桌面 GUI |
| opencv-python | 影片讀寫 |
| ultralytics | YOLOv8 人物追蹤 |
| pandas | 對話腳本讀取 |
| pillow | 氣泡繪製 |
| faster-whisper | 語音辨識（可選） |
| ffmpeg（系統） | 影片編碼輸出 |

---

## 授權

MIT License — 詳見 [LICENSE](LICENSE)
