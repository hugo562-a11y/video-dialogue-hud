# 影片對話 HUD 工具 - SKILL 文檔總索引

完整的工具功能文檔已整理成 SKILL 格式，便於快速查詢和參考。

## 📚 SKILL 文檔清單

### 1. [SKILL_UI_Design.md](SKILL_UI_Design.md) - UI 設計
**主要內容**:
- 主視窗架構 (1500x860 像素，暗色主題)
- 左側邊欄 (220px 寬，工作流程按鈕)
- 中央預覽區 (Canvas 畫布，支援平移和縮放)
- 右側腳本面板 (動態對話列表，支援編輯)
- 時間軸區域 (播放控制和波形顯示)
- 配色系統 (8 色調色盤 + 特殊狀態色)
- 字體設定 (微軟正黑體，12-20px)
- 鍵盤快捷鍵綁定 (15+ 個快捷鍵)
- 回應式設計 (最小 1180x720，彈性佈局)

**快速查詢**: UI 佈局、顏色代碼、字體、快捷鍵

---

### 2. [SKILL_Timeline_Waveform.md](SKILL_Timeline_Waveform.md) - 時間軸與波形功能
**主要內容**:
- 波形生成流程 (FFmpeg → WAV → 音頻採樣 → 峰值)
- 波形顯示與交互 (繪製、滾輪縮放、拖曳平移)
- 滾動顯示比例 (自適應縮放 0.1x - 10x)
- 時間軸句柄與邊界調整
  - 句首句尾設定 (句柄拖曳，快捷鍵微調)
  - 平移範圍檢查 (邊界限制，最小 0.05 秒間隔)
  - 波形句柄管理 (位置記錄，色彩編碼)
- 波形區域交互總結 (操作列表)
- 時間轉換工具 (幀 ↔ 秒轉換，時間字符串解析)
- 波形緩存與效能 (快取機制，清理操作)
- 實時更新流程 (隊列驅動)

**快速查詢**: 時間軸調整、波形縮放、句柄拖曳、時間解析

---

### 3. [SKILL_Script_Editing.md](SKILL_Script_Editing.md) - 腳本編輯功能
**主要內容**:
- 腳本面板結構 (行容器組成、顏色狀態)
- 腳本編輯操作
  1. **新增對話** - 在當前時間軸位置插入新句
  2. **刪除對話** - 軟刪除機制，支援還原
  3. **修改對話** - 發言人、文本、時間微調
  4. **合併對話** - 將兩句合併為一句
  5. **斷句** - 在光標位置分割句子
- 撤銷/重做系統 (詳見第 5 個文檔)
- 批量操作 (刪除所有無講話行、全選/反選)
- 行刷新最佳化 (增量更新、自動滾動)
- 性能考慮 (大型腳本優化、撤銷棧限制)

**快速查詢**: 新增、刪除、修改、合併、斷句操作

---

### 4. [SKILL_Script_UI_Display.md](SKILL_Script_UI_Display.md) - 腳本面板字句顯示
**主要內容**:
- 行狀態分類 (已選中、無講話、已刪除)
- 行背景與邊框 (狀態色 8 色組合)
- 字體與文本樣式 (加粗、刪除線、灰色)
- 時間按鈕 (98px，顯示格式 MM:SS)
- 發言人欄位 (ComboBox，支援自由輸入)
- 對話文本欄位 (Entry，即時更新)
- 操作按鈕區 (刪除/還原/新增)
- 特殊行類型 (無講話行、已刪除行)
- 選中狀態視覺化 (藍色背景 + 黃金邊框)
- 行寬度與佈局 (Grid 佈局，響應式寬度)
- 行邊距與間距 (精確像素距離)
- 性能最佳化 (UI 組件快取、虛擬滾動)

**快速查詢**: 行顏色、按鈕樣式、文本格式、視覺狀態

---

### 5. [SKILL_Undo_Redo_System.md](SKILL_Undo_Redo_System.md) - 撤銷/重做系統
**主要內容**:
- 核心概念 (狀態快照、棧結構)
- 撤銷操作流程
  - 記錄撤銷點 (`push_undo_state`)
  - 執行撤銷 (`Ctrl+Z`)
  - 執行重做 (`Ctrl+Y`)
- 狀態復原流程 (數據層、播放器、選中、快取、UI)
- 文本編輯撤銷組 (避免文字輸入爆炸)
- 特定操作的撤銷標籤 (8+ 種操作分類)
- 撤銷限制與記憶體管理 (預設 80 步，~80MB)
- 邊界情況處理 (空棧、失敗、分支)
- 鍵盤快捷鍵 (Ctrl+Z / Ctrl+Y)
- 日誌記錄 (操作時間線)
- 測試場景 (9+ 個測試用例)
- 未來改進 (粒度控制、可視化、自動保存)

**快速查詢**: 撤銷重做原理、快捷鍵、限制、測試

---

## 🎯 按功能快速查詢

| 功能需求 | 參考文檔 | 章節 |
|---------|--------|------|
| **界面設計** | UI_Design | 主視窗架構、配色系統、字體 |
| **時間軸調整** | Timeline_Waveform | 句首句尾設定、平移範圍 |
| **波形顯示** | Timeline_Waveform | 波形生成、滾輪縮放、拖曳 |
| **時間格式** | Timeline_Waveform | 時間轉換工具、字符串解析 |
| **新增對話** | Script_Editing | 新增對話操作 |
| **刪除對話** | Script_Editing | 刪除對話操作 |
| **修改發言人** | Script_Editing | 修改對話 → 發言人修改 |
| **修改文本** | Script_Editing | 修改對話 → 文本修改 |
| **合併句子** | Script_Editing | 合併對話操作 |
| **斷句** | Script_Editing | 斷句操作 |
| **行顏色** | Script_UI_Display | 行背景與邊框、配色盤 |
| **行按鈕** | Script_UI_Display | 時間按鈕、操作按鈕 |
| **撤銷重做** | Undo_Redo_System | 撤銷操作流程、狀態復原 |
| **快捷鍵** | UI_Design / Undo_Redo | 鍵盤快捷鍵綁定 |
| **效能優化** | Script_Editing / UI_Display | 行刷新、虛擬滾動、緩存 |

---

## 💡 常見問題與答案

### Q: 如何新增一句對話？
**A**: 參考 [Script_Editing.md](SKILL_Script_Editing.md#2-新增對話-insert-dialogue) - 新增對話章節

### Q: 時間軸按鈕的顏色代碼是什麼？
**A**: 參考 [Script_UI_Display.md](SKILL_Script_UI_Display.md#時間按鈕-time-display--button) - 時間按鈕配置

### Q: 如何調整對話的開始時間？
**A**: 參考 [Timeline_Waveform.md](SKILL_Timeline_Waveform.md#句首句尾設定-start-time) - 句首調整

### Q: 撤銷棧的最大深度是多少？
**A**: 參考 [Undo_Redo_System.md](SKILL_Undo_Redo_System.md#撤銷限制與記憶體管理) - 預設 80 步

### Q: 如何修改發言人名稱？
**A**: 參考 [Script_Editing.md](SKILL_Script_Editing.md#發言人修改) - 修改對話 → 發言人修改

### Q: 波形的縮放範圍是多少？
**A**: 參考 [Timeline_Waveform.md](SKILL_Timeline_Waveform.md#滾輪操作) - 縮放限制 0.1x - 10x

### Q: 無講話行如何顯示？
**A**: 參考 [Script_UI_Display.md](SKILL_Script_UI_Display.md#無講話行-silence-rows) - 特殊行類型

### Q: 為什麼文字編輯不會產生過多的撤銷點？
**A**: 參考 [Undo_Redo_System.md](SKILL_Undo_Redo_System.md#文本編輯撤銷組) - 文本編輯撤銷組機制

---

## 📖 文檔使用建議

1. **首次瞭解工具**: 依序閱讀 UI_Design → Timeline_Waveform → Script_Editing
2. **開發新功能**: 查詢相關 SKILL，瞭解現有實現方式
3. **修復 Bug**: 查詢相關功能的 SKILL，檢查邊界情況和測試場景
4. **效能最佳化**: 查詢相關 SKILL 的「效能」章節
5. **文檔維護**: 修改代碼後，同步更新對應 SKILL 中的代碼片段

---

## 📝 SKILL 文檔規範

每個 SKILL 文檔包含：

- **概述**: 功能簡介
- **核心概念**: 基本原理
- **代碼示例**: 關鍵實現
- **操作指南**: 使用方式
- **表格**: 快速參考 (顏色、快捷鍵等)
- **邊界情況**: 特殊處理
- **性能考慮**: 最佳實踐
- **測試場景**: 驗證方式

---

## 🔗 相關檔案

- **源代碼**: `ui/`, `core/` 目錄
- **主入口**: `main.py`, `agentic_hud_tool.py`
- **配置**: `core/constants.py`
- **工具函數**: `core/utils.py`

---

## 📌 版本資訊

- **建立日期**: 2026-05-23
- **工具版本**: 影片對話 HUD v1.0
- **框架**: CustomTkinter + OpenCV + YOLO
- **文檔版本**: 1.0

---

## ✅ 下次更新清單

- [ ] 新增預覽區 Canvas 的繪製細節 (SKILL_Preview.md)
- [ ] 新增 YOLO 人物檢測和標框繪製 (SKILL_Detection.md)
- [ ] 新增匯出和視頻渲染流程 (SKILL_Export.md)
- [ ] 新增資料處理和 CSV 操作 (SKILL_DataProcessor.md)
- [ ] 新增測試和 Debug 指南 (SKILL_Testing.md)

---

💾 **所有文檔已保存至**: `docs/` 目錄
