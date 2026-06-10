# SKILL: 腳本編輯功能

## 概述

腳本編輯功能提供完整的對話管理系統，包括新增、刪除、修改、合併、微調等操作，以及完整的撤銷/重做支援。

## 腳本面板結構

### 面板設定

```python
# 主要屬性
script_row_widgets = {}        # 儲存各行的 UI 組件引用
selected_dialogue_row = None   # 當前選中的對話行編號
_script_row_loading = False    # 防止遞迴載入標誌
```

### 行容器組成

#### 1. 時間按鈕 (Time Button)
- **顯示**: 格式化的開始時間（例: "0:30"）
- **尺寸**: 寬 98px，高 26-28px
- **功能**: 點擊跳轉到該時間點並播放
- **樣式**:
  - 正常: `#334155` 背景
  - 刪除: `#5B2B34` (暗紅)
  - 懸停: 變亮 (3px)

```python
time_btn = ctk.CTkButton(
    line, text=time_text or "--:--",
    width=98, height=26 if is_silence else 28,
    fg_color="#5B2B34" if is_deleted else "#334155",
    hover_color="#73323E" if is_deleted else "#475569",
    command=lambda idx=row_idx: self.select_dialogue_row(idx, seek=True),
)
```

#### 2. 發言人欄位 (Speaker ComboBox)
- **組件**: CTkComboBox (下拉式選單)
- **值清單**: 所有已知人物 + 可直接輸入新名稱
- **交互**: 
  - 點擊開啟下拉菜單
  - 輸入新文本自動新增人物
  - 失焦時自動保存

```python
combo_speaker = ctk.CTkComboBox(
    line, 
    values=speakers,
    command=lambda v: update_dialogue_speaker(row_idx, v),
    height=28,
)
combo_speaker.set(speaker)
```

#### 3. 對話文本欄位 (Text Entry)
- **組件**: CTkEntry (單行文本輸入)
- **驗證**: 實時同步到數據層
- **特殊狀態**: 
  - 刪除時使用刪除線字體
  - 「無講話」行隱藏此欄位

```python
entry_text = ctk.CTkEntry(
    line,
    textvariable=tk.StringVar(value=text),
)
entry_text.bind("<FocusOut>", on_text_change)
entry_text.bind("<KeyRelease>", on_text_editing)
```

#### 4. 操作按鈕 (Action Buttons)

##### 刪除/還原按鈕
```python
# 已刪除的行
btn_restore = ctk.CTkButton(
    line, text="還", width=28, height=28,
    fg_color="#2E5B8B", hover_color="#3572A5",
    command=lambda idx=row_idx: restore_dialogue(idx),
)

# 未刪除的行
btn_delete = ctk.CTkButton(
    line, text="刪", width=28, height=28,
    fg_color="#5B2B34", hover_color="#7B3B4C",
    command=lambda idx=row_idx: delete_dialogue(idx),
)
```

##### 新增按鈕 (行尾)
```python
btn_add_after = ctk.CTkButton(
    line, text="➕", width=28, height=28,
    fg_color="#2E5B3E", hover_color="#3F8B55",
    command=lambda idx=row_idx: insert_after(idx),
)
```

## 腳本編輯操作

### 1. 新增對話 (Insert Dialogue)

#### 按鈕操作
```python
def add_sentence_at_current_time():
    """在當前時間軸位置新增一句對話"""
    
    # 1. 取得當前時間
    frame_idx = int(float(self.slider_timeline.get()))
    start = frame_to_seconds(frame_idx, self.renderer.fps)
    end = min(start + 2.0, video_duration)
    
    # 2. 取得發言人和文本
    speaker = self.entry_speaker.get().strip() or default_speaker
    text = self.entry_text.get().strip() or "新增對話"
    
    # 3. 記錄撤銷點
    self.push_undo_state("新增句")
    
    # 4. 插入到數據層
    row_idx = self.renderer.data_processor.insert_dialogue_row(
        start, end, speaker, text
    )
    
    # 5. 更新 UI
    self.selected_dialogue_row = row_idx
    self.renderer.bubble_cache.clear()
    self.refresh_script_panel()
    self.slider_timeline.set(frame_idx)
    self.refresh_current_preview()
```

#### 快捷方式
- **面板內新增**: 在任意行右側點擊 「➕」 按鈕
- **時間軸拖曳**: 雙擊波形區域創建新對話

#### 預設值
- **起始時間**: 當前時間軸位置
- **結束時間**: 起始時間 + 2.0 秒（或到影片結尾）
- **發言人**: 當前選中人物
- **文本**: 「新增對話」(可立即編輯)

### 2. 刪除對話 (Delete Dialogue)

#### 邏輯
- **軟刪除**: 標記為已刪除，不實際移除
- **匯出時**: 自動剪去已刪除的片段
- **還原**: 可隨時還原已刪除的對話

#### 操作方式

##### 鍵盤快捷鍵
```python
def delete_selected_dialogue(event=None):
    """按 Delete 鍵刪除/還原"""
    
    # 檢查當前焦點是否在輸入框中
    if widget_class in {"Entry", "Text"}:
        return  # 在輸入框中，允許刪除文字
    
    # 取得當前選中行
    row_idx = self.selected_dialogue_row
    if row_idx is None or not dp.has_data():
        return
    
    # 反轉刪除狀態
    deleted = not dp.is_deleted(row_idx)
    self.push_undo_state("刪除句" if deleted else "還原句")
    
    # 更新數據層
    dp.set_deleted(row_idx, deleted)
    
    # 更新 UI
    self.renderer.bubble_cache.clear()
    self.refresh_script_panel()
    self.refresh_current_preview()
```

##### 面板按鈕
- 每行右側有 「刪」(紅色) 或 「還」(藍色) 按鈕

#### 視覺反饋
- **刪除時**: 行背景變暗紅 `#4A2630`，文本加刪除線
- **還原時**: 恢復原色和正常文本

### 3. 修改對話 (Edit Dialogue)

#### 發言人修改

```python
def update_dialogue_speaker(row_idx, new_speaker):
    """修改發言人"""
    dp = self.renderer.data_processor
    
    # 同步到 YOLO ID 映射
    tid = current_person_id
    if new_speaker:
        self.renderer.yolo_id_to_speaker[tid] = new_speaker
    
    # 更新數據層
    dp.update_dialogue_speaker(row_idx, new_speaker)
    
    # 記錄撤銷
    self.push_undo_state("修改說話者")
    
    # 更新 UI
    self.renderer.bubble_cache.clear()
    self.refresh_script_panel()
    self.refresh_current_preview()
```

#### 文本修改

```python
def update_dialogue_text(row_idx, new_text):
    """修改對話文本"""
    dp = self.renderer.data_processor
    
    # 開始文本撤銷組 (避免每字一次撤銷)
    self.begin_text_undo_group()
    
    # 更新數據層
    dp.update_dialogue_text(row_idx, new_text)
    
    # UI 實時更新
    self.refresh_current_preview()
```

#### 時間微調

```python
def nudge_dialogue_edge(edge, delta, event=None):
    """微調句子邊界時間"""
    # edge: "start" 或 "end"
    # delta: 時間增量（秒）
    
    dp = self.renderer.data_processor
    row_idx = self.selected_dialogue_row
    
    if row_idx is None:
        return
    
    # 取得當前時間範圍
    start, end = parse_time_range(dp.get_dialogue_time(row_idx))
    
    # 調整邊界
    if edge == "start":
        start = max(0.0, min(end - 0.05, start + delta))
    else:
        end = max(start + 0.05, end + delta)
    
    # 記錄撤銷
    self.push_undo_state("微調句子時間")
    
    # 更新數據層
    dp.update_dialogue_time(row_idx, start, end)
    
    # 更新 UI
    self.refresh_script_panel()
    self.refresh_current_preview()
```

| 快捷鍵 | 功能 |
|--------|------|
| `[` | 句首後退 50ms |
| `]` | 句尾前進 50ms |
| `Shift+[` | 句首前進 50ms |
| `Shift+]` | 句尾後退 50ms |

### 4. 合併對話 (Merge Dialogue)

```python
def merge_selected_dialogue():
    """將當前行與下一行合併"""
    dp = self.renderer.data_processor
    row_idx = self.selected_dialogue_row
    
    if row_idx is None or not dp.has_data():
        return
    
    # 記錄撤銷點
    self.push_undo_state("合併句")
    
    # 合併邏輯
    success, message = dp.merge_dialogue_rows(row_idx)
    
    if success:
        # 合併會導致下一行刪除，當前行擴展
        self.renderer.bubble_cache.clear()
        self.refresh_script_panel()
        self.refresh_current_preview()
    
    self.log(message)
```

**合併規則**:
- 合併當前行和下一行
- 保留兩行的最早開始時間和最晚結束時間
- 文本合併: 「人物 A: 文本 A + 人物 B: 文本 B」
- 發言人: 選擇當前行的發言人

### 5. 斷句 (Split Dialogue)

```python
def split_current_sentence():
    """在光標位置將句子斷開"""
    
    # 檢查是否有選中的行
    if self.selected_dialogue_row is None:
        messagebox.showinfo(APP_TITLE, "請先點選一個有對話的泡泡。")
        return
    
    # 取得光標位置
    text, cursor_pos = self.current_dialogue_text_and_cursor()
    
    if len(text.strip()) < 2:
        messagebox.showinfo(APP_TITLE, "這句太短，無法斷句。")
        return
    
    # 記錄撤銷
    self.push_undo_state("切斷句")
    
    # 執行斷句
    success, message, new_row_idx = self.renderer.data_processor.split_dialogue_row(
        self.selected_dialogue_row, cursor_pos
    )
    
    if success:
        self.selected_dialogue_row = new_row_idx
        self.renderer.bubble_cache.clear()
        self.refresh_script_panel()
        self.refresh_current_preview()
    
    self.log(message)
```

**斷句過程**:
1. 在光標位置分割文本
2. 計算中點時間
3. 前半句: 原開始時間 → 中點時間
4. 後半句: 中點時間 → 原結束時間
5. 兩句保持相同的發言人

## 撤銷/重做 (Undo/Redo)

### 撤銷棧結構

```python
# 撤銷狀態快照
{
    "label": "新增句",           # 操作描述
    "df": DataFrame,             # 完整數據副本
    "df_path": str,              # 檔案路徑
    "cut_ranges": list,          # 裁剪範圍
    "speakers": dict,            # 人物映射
    "person_styles": dict,       # 人物樣式
    "bubble_offsets": dict,      # 泡泡偏移
    "selected_row": int,         # 選中行
}
```

### 操作管理

#### 記錄撤銷點

```python
def push_undo_state(label=""):
    """記錄當前狀態以供撤銷"""
    state = self.snapshot_state(label)
    self.undo_stack.append(state)
    
    # 限制棧深度 (預設 80 步)
    if len(self.undo_stack) > self._undo_limit:
        self.undo_stack.pop(0)
    
    # 執行新操作時清空重做棧
    self.redo_stack.clear()
```

#### 撤銷操作

```python
def undo_action(event=None):
    """Ctrl+Z - 撤銷上一個操作"""
    
    if not self.undo_stack:
        return "break"
    
    # 當前狀態入重做棧
    self.redo_stack.append(self.snapshot_state("redo"))
    
    # 復原到上一個狀態
    state = self.undo_stack.pop()
    self.restore_state(state)
    
    self.log(f"Undo: {state.get('label')}")
    return "break"
```

#### 重做操作

```python
def redo_action(event=None):
    """Ctrl+Y - 重做上一個撤銷的操作"""
    
    if not self.redo_stack:
        return "break"
    
    # 當前狀態入撤銷棧
    self.undo_stack.append(self.snapshot_state("undo"))
    
    # 復原到下一個狀態
    state = self.redo_stack.pop()
    self.restore_state(state)
    
    self.log(f"Redo: {state.get('label')}")
    return "break"
```

### 快捷鍵綁定

| 快捷鍵 | 功能 |
|--------|------|
| `Ctrl+Z` | 撤銷 |
| `Ctrl+Y` | 重做 |

### 文本編輯撤銷組

防止編輯文本時每按一個字就產生一個撤銷點：

```python
def begin_text_undo_group(event=None):
    """開始文本編輯會話"""
    if self.selected_dialogue_row is None:
        return
    self._typing_undo_row = self.selected_dialogue_row
    self._typing_undo_original = self.entry_text.get()

def end_text_undo_group(event=None):
    """結束文本編輯會話，記錄撤銷點"""
    if self._typing_undo_original != self.entry_text.get():
        self.push_undo_state("編輯文本")
    self._typing_undo_row = None
    self._typing_undo_original = None
```

### 復原狀態更新流程

```python
def restore_state(state):
    """復原到特定狀態"""
    dp = self.renderer.data_processor
    
    # 1. 復原數據
    dp.df = state["df"].copy(deep=True) if state["df"] else None
    
    # 2. 復原映射和配置
    self.renderer.yolo_id_to_speaker = dict(state["speakers"])
    self.renderer.person_styles = {
        tid: dict(s) for tid, s in state["person_styles"].items()
    }
    self.renderer.bubble_offsets = dict(state["bubble_offsets"])
    
    # 3. 復原選中行
    self.selected_dialogue_row = state["selected_row"]
    
    # 4. 清除緩存並刷新界面
    self.renderer.bubble_cache.clear()
    self.refresh_after_state_restore()
```

## 批量操作

### 刪除所有「無講話」行

```python
def delete_all_silence_rows():
    """批量刪除所有「無講話」的行"""
    dp = self.renderer.data_processor
    speaker_col = dp.get_columns()[1]
    
    if speaker_col is None:
        return
    
    self.push_undo_state("刪除所有無講話")
    
    count = 0
    for row_idx, row in dp.df.iterrows():
        speaker = str(row[speaker_col]).strip()
        if speaker == SILENCE_SPEAKER:
            dp.set_deleted(row_idx, True)
            count += 1
    
    self.log(f"已刪除 {count} 句無講話行。")
    self.refresh_script_panel()
    self.refresh_current_preview()
```

### 全選/反選

```python
def select_all_dialogues():
    """選中所有對話"""
    if self.renderer.data_processor.has_data():
        self.selected_all = True
        self.refresh_script_panel()

def deselect_all_dialogues():
    """取消選中所有對話"""
    self.selected_all = False
    self.selected_dialogue_row = None
    self.refresh_script_panel()
```

## 行刷新最佳化

### 增量更新

```python
def refresh_script_panel(self):
    """智能刷新面板"""
    
    # 如果行數沒變，只更新內容
    if same_row_count:
        for row_idx in changed_rows:
            self.update_script_row_deleted_state(row_idx)
    else:
        # 否則重新建構整個面板
        self.refresh_script_panel_full()
```

### 自動滾動

```python
def select_dialogue_row(row_idx, seek=False):
    """選中對話並自動滾動到視圖內"""
    self.selected_dialogue_row = row_idx
    
    if seek and self.slider_timeline.cget("state") == "normal":
        # 跳轉到對應的時間
        frame = seconds_to_frame(start_time, self.renderer.fps)
        self.slider_timeline.set(frame)
    
    # 自動滾動腳本面板
    self.script_scroll.yview_moveto(row_widget_position)
```

## 性能考慮

### 大型腳本優化
- 只為可見行創建 UI 組件 (虛擬滾動)
- 使用 `_script_row_loading` 標誌防止遞迴更新
- 對大批量操作使用暫停渲染

### 撤銷棧限制
- 預設深度: 80 步
- 可根據內存調整: `self._undo_limit`
- 自動刪除最舊的快照
