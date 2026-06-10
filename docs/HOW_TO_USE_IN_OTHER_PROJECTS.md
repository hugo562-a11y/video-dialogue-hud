# 如何在其他專案中使用 SKILL 文檔

## 概述

這些 SKILL 文檔可以被其他開發者、項目或團隊直接引用。以下是多種使用方式。

---

## 方式 1️⃣ - VS Code 中直接引用

### 步驟

1. **複製文檔到項目**
   ```
   其他專案/
   ├── docs/
   │   ├── SKILL_UI_Design.md           (從這裡複製)
   │   ├── SKILL_Timeline_Waveform.md
   │   ├── SKILL_Script_Editing.md
   │   ├── SKILL_Script_UI_Display.md
   │   ├── SKILL_Undo_Redo_System.md
   │   └── README.md
   ```

2. **在 VS Code 中打開和查詢**
   - `Ctrl+P` 搜索 `SKILL_` 快速打開
   - `Ctrl+F` 搜索關鍵詞 (例: "撤銷", "顏色代碼")
   - 點擊表格中的超鏈接跳轉相關章節

3. **按功能快速查詢**
   - 打開 `docs/README.md` 的 「按功能快速查詢」表格
   - 找到相關功能對應的文檔和章節

### 優點
- ✅ 完全本地化，無需網絡
- ✅ 可搜索，支援全文搜索
- ✅ 支援 Markdown 預覽
- ✅ 易於版本控制 (git)

---

## 方式 2️⃣ - GitHub/Gitee 中發佈

### 步驟

1. **上傳到版本庫**
   ```bash
   git clone <你的項目>
   cp -r 影片追踪工具/docs/ 你的項目/docs/skill/
   cd 你的項目
   git add docs/skill/
   git commit -m "docs: 添加 HUD 工具 SKILL 文檔"
   git push
   ```

2. **在 README 中引用**
   ```markdown
   ## 📚 技術文檔
   
   - [HUD 工具 SKILL 文檔](./docs/skill/README.md)
     - [UI 設計](./docs/skill/SKILL_UI_Design.md)
     - [時間軸功能](./docs/skill/SKILL_Timeline_Waveform.md)
     - [腳本編輯](./docs/skill/SKILL_Script_Editing.md)
     - [撤銷重做](./docs/skill/SKILL_Undo_Redo_System.md)
   ```

3. **在代碼中註釋中引用**
   ```python
   """
   時間軸调整功能
   
   參考文檔: ../docs/skill/SKILL_Timeline_Waveform.md
   """
   def nudge_dialogue_edge(edge, delta, event=None):
       ...
   ```

### 優點
- ✅ 團隊共享，便於協作
- ✅ GitHub Pages 自動渲染
- ✅ 版本管理，追蹤修改
- ✅ 可搜索，易於搜索引擎收錄

---

## 方式 3️⃣ - 作為項目模板參考

### 使用場景

當您要開發類似的工具時：

**創建新項目的步驟**

1. **複製架構**
   ```
   新UI工具/
   ├── ui/
   │   ├── app.py              (參考 SKILL_UI_Design.md)
   │   ├── waveform.py         (參考 SKILL_Timeline_Waveform.md)
   │   ├── script_panel.py     (參考 SKILL_Script_Editing.md)
   │   ├── editing.py
   │   └── ...
   ├── core/
   │   ├── constants.py
   │   ├── data_processor.py
   │   └── ...
   └── docs/
       └── SKILL_*.md          (複製這些文檔)
   ```

2. **按 SKILL 文檔開發新功能**
   - 讀 `SKILL_UI_Design.md` → 建構 UI 架構
   - 讀 `SKILL_Timeline_Waveform.md` → 實現時間軸
   - 讀 `SKILL_Script_Editing.md` → 實現編輯功能
   - 讀 `SKILL_Undo_Redo_System.md` → 實現撤銷重做

3. **驗證實現**
   - 對照 SKILL 文檔中的代碼示例
   - 參考「邊界情況」章節避免常見 Bug
   - 按「測試場景」驗證功能

### 代碼片段直接複用

**例如：配色系統**
```python
# 參考: SKILL_UI_Design.md → 配色系統
SPEAKER_PALETTE = [
    ("#173B45", "#38BDF8"),
    ("#3B2A50", "#A78BFA"),
    ("#23462F", "#4ADE80"),
    ...
]

def speaker_palette(self, speaker: str) -> tuple[str, str]:
    """參考 SKILL_Script_Editing.md 的實現"""
    key = sum(ord(ch) for ch in speaker) if speaker else 0
    return self.SPEAKER_PALETTE[key % len(self.SPEAKER_PALETTE)]
```

**例如：撤銷重做**
```python
# 參考: SKILL_Undo_Redo_System.md → 核心概念
def push_undo_state(self, label=""):
    """複製此方法到您的項目"""
    state = self.snapshot_state(label)
    self.undo_stack.append(state)
    if len(self.undo_stack) > self._undo_limit:
        self.undo_stack.pop(0)
    self.redo_stack.clear()
```

### 優點
- ✅ 快速學習工程最佳實踐
- ✅ 減少開發時間
- ✅ 確保代碼質量
- ✅ 統一的設計模式

---

## 方式 4️⃣ - 團隊知識庫

### 內部文檔管理

1. **複製到企業 Wiki/知識庫**
   - 內網 Confluence / 飛書 / 語雀 / Notion
   - 複製 Markdown 內容並轉換格式

2. **組織結構**
   ```
   技術文檔/
   └── 前端開發/
       ├── UI 設計指南
       ├── CustomTkinter 實踐
       │   └── 影片對話 HUD 工具 SKILL 文檔
       │       ├── UI 設計
       │       ├── 時間軸功能
       │       ├── 腳本編輯
       │       └── 撤銷重做
       └── 其他工具...
   ```

3. **標籤和分類**
   - 標籤: `CustomTkinter`, `UI`, `時間軸`, `撤銷重做`
   - 團隊: 前端、工具開發
   - 狀態: 已完成、已驗證、推薦使用

### 優點
- ✅ 集中管理，便於查詢
- ✅ 供全團隊參考學習
- ✅ 建立知識積累
- ✅ 新人快速上手

---

## 方式 5️⃣ - 課程/教程材料

### 教學應用

**場景 1: CustomTkinter UI 開發課程**
```
第 1 章: UI 架構設計
  → 參考: SKILL_UI_Design.md

第 2 章: 時間軸控件實現
  → 參考: SKILL_Timeline_Waveform.md

第 3 章: 數據編輯和同步
  → 參考: SKILL_Script_Editing.md

第 4 章: 操作歷史管理
  → 參考: SKILL_Undo_Redo_System.md
```

**場景 2: UI/UX 設計案例研究**
- 分析配色系統 (SKILL_UI_Design.md)
- 學習響應式設計 (SKILL_UI_Design.md)
- 研究視覺反饋機制 (SKILL_Script_UI_Display.md)

**場景 3: 軟件工程最佳實踐**
- 撤銷重做架構 (SKILL_Undo_Redo_System.md)
- 狀態管理模式 (SKILL_Undo_Redo_System.md)
- 性能優化 (各文檔)

### 優點
- ✅ 真實項目案例
- ✅ 完整的技術細節
- ✅ 可供學生參考
- ✅ 提升課程質量

---

## 方式 6️⃣ - 技術博客/文章

### 發布選項

1. **個人博客**
   ```markdown
   ---
   title: 用 CustomTkinter 構建音視頻編輯 UI
   tags: [CustomTkinter, Python UI, 教程]
   date: 2026-05-23
   ---
   
   我分析了一個完整的音視頻編輯工具的實現...
   
   [完整 SKILL 文檔下載](link-to-docs)
   ```

2. **掘金/知乎/Medium 文章**
   - 摘要核心內容
   - 鏈接到完整文檔
   - 分享學到的最佳實踐

3. **GitHub Discussions/Issues**
   - 引用相關 SKILL 文檔章節
   - 幫助其他開發者理解實現

### 優點
- ✅ 分享知識，幫助社區
- ✅ 建立個人品牌
- ✅ 獲得反饋和討論
- ✅ SEO 流量

---

## 方式 7️⃣ - 代碼審查參考

### 代碼審查流程

**在 GitHub PR 中引用 SKILL 文檔**

```
### 審查清單

- [ ] UI 組件符合設計規範 (SKILL_UI_Design.md)
- [ ] 時間軸交互邏輯正確 (SKILL_Timeline_Waveform.md)
- [ ] 編輯操作已記錄撤銷點 (SKILL_Undo_Redo_System.md)
- [ ] 已完成性能測試 (相關 SKILL 中的性能考慮)

參考文檔: https://github.com/xxx/docs/skill/README.md
```

**代碼註釋中使用**

```python
def update_dialogue_speaker(row_idx, speaker):
    """
    修改發言人
    
    參考: SKILL_Script_Editing.md#發言人修改
    確保同步 YOLO ID 映射和數據層
    """
    # 實現...
```

### 優點
- ✅ 審查有據可依
- ✅ 減少討論成本
- ✅ 統一編碼標準
- ✅ 知識傳承

---

## 方式 8️⃣ - API/模塊文檔

如果將 HUD 工具封裝為模塊供他人使用：

### 模塊化示例

```python
# videohud/ui/waveform.py
"""
波形顯示和交互模塊

參考完整文檔: ../../../docs/SKILL_Timeline_Waveform.md

使用示例:
    from videohud.ui.waveform import WaveformMixin
    
    class MyApp(WaveformMixin, ctk.CTk):
        def __init__(self):
            super().__init__()
            self._setup_waveform()
"""

class WaveformMixin:
    """
    提供波形顯示、縮放和拖曳功能
    
    詳見: SKILL_Timeline_Waveform.md
    
    屬性:
        waveform_samples: 音頻峰值數組
        waveform_duration: 音頻時長
        waveform_view_start/end: 當前顯示範圍
    
    方法:
        _generate_waveform(): 從視頻生成波形
        on_waveform_scroll(): 滾輪縮放
        on_waveform_drag(): 平移和調整
    """
```

### 優點
- ✅ 模塊化設計清晰
- ✅ API 文檔完整
- ✅ 易於集成和複用
- ✅ 降低使用門檻

---

## 快速參考清單 📋

| 使用方式 | 場景 | 優點 |
|---------|------|------|
| 1. VS Code 本地 | 同項目開發 | 快速查詢、無需網絡 |
| 2. GitHub 發佈 | 團隊共享 | 版本管理、可搜索 |
| 3. 項目模板 | 新項目開發 | 快速上手、複用代碼 |
| 4. 知識庫 | 企業內部 | 集中管理、知識積累 |
| 5. 課程材料 | 教學培訓 | 真實案例、完整細節 |
| 6. 技術文章 | 社區分享 | 知識傳播、個人品牌 |
| 7. 審查參考 | 代碼審查 | 有據可依、統一標準 |
| 8. 模塊文檔 | API 文檔 | 模塊化、易於集成 |

---

## 授權和使用條款

### 開源協議

這些 SKILL 文檔和源代碼可根據以下方式使用：

- ✅ **自由複製和引用** - 在其他專案中使用
- ✅ **修改和調整** - 適應您的項目需要
- ✅ **商業使用** - 用於商業項目
- ✅ **署名** - 建議但非強制性註明出處

### 推薦格式

```
此項目參考或基於「影片對話 HUD 工具」SKILL 文檔
https://github.com/xxx/影片追踪工具
```

---

## 後續支援

### 如何提出問題或改進

1. **發現文檔錯誤？**
   - 提交 Issue 說明位置和問題

2. **想補充新內容？**
   - 提交 PR 或建議

3. **需要相關工具的 SKILL？**
   - 聯繫原作者或社區貢獻

4. **建立專案間引用？**
   - 在 GitHub README 中添加鏈接

---

## 常見 Q&A

**Q: 可以直接複製代碼到我的項目嗎？**
A: 可以。代碼示例可直接複用，建議加上註釋說明來源。

**Q: 文檔需要更新時怎麼辦？**
A: 建議維護一個本地副本並標記修改日期，或提交 PR 貢獻回原項目。

**Q: 能在商業項目中使用嗎？**
A: 可以。開源協議允許商業使用，建議註明出處。

**Q: 如何將文檔轉換為其他格式？**
A: Markdown 可轉換為 HTML、PDF (Pandoc)、DOCX (Typora) 等。

**Q: 可以翻譯為其他語言嗎？**
A: 可以。翻譯後建議提交 PR 貢獻回社區。

---

## 相關鏈接

- 📁 原始項目: `z:\!影片追踪工具\`
- 📚 文檔目錄: `docs/`
- 🔍 快速查詢: `docs/README.md`
- 💻 源代碼: `ui/`, `core/`

---

**更新於**: 2026-05-23  
**文檔版本**: 1.0  
**狀態**: ✅ 完成並可供使用
