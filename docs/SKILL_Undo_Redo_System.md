# SKILL: 撤銷/重做系統

## 概述

撤銷/重做系統提供完整的操作歷史管理，使用戶能夠快速恢復或重做任何修改。系統採用快照機制，記錄應用程序的完整狀態。

## 核心概念

### 狀態快照 (State Snapshot)

每次記錄撤銷點時，系統會建立一個完整的應用狀態副本：

```python
def snapshot_state(label=""):
    dp = self.renderer.data_processor
    return {
        "label": label,                      # 操作描述，用於日誌
        "df": None if dp.df is None else dp.df.copy(deep=True),  # 深拷貝數據表
        "df_path": dp.path,                  # 腳本檔案路徑
        "cut_ranges": list(self.renderer.cut_ranges),             # 裁剪範圍列表
        "speakers": dict(self.renderer.yolo_id_to_speaker),       # 人物 ID 映射
        "person_styles": {                   # 人物樣式 (顏色等)
            tid: dict(style) 
            for tid, style in self.renderer.person_styles.items()
        },
        "bubble_offsets": dict(self.renderer.bubble_offsets),     # 泡泡位置偏移
        "selected_row": self.selected_dialogue_row,               # 當前選中行
    }
```

**關鍵點**:
- **深拷貝**: `df.copy(deep=True)` 確保數據獨立
- **完整狀態**: 包含所有與編輯相關的數據
- **標籤**: 用於 UI 日誌，幫助用戶識別操作

### 棧結構

```python
# 撤銷棧: 儲存已執行的操作
self.undo_stack = []  # 最多 80 個狀態

# 重做棧: 儲存已撤銷的操作
self.redo_stack = []

# 限制深度
self._undo_limit = 80  # 可調整
```

**棧演變示例**:
```
初始狀態: undo=[], redo=[]
操作 A:   undo=[A], redo=[]
操作 B:   undo=[A,B], redo=[]
撤銷:     undo=[A], redo=[B]
重做:     undo=[A,B], redo=[]
```

## 撤銷操作流程

### 記錄撤銷點

```python
def push_undo_state(label=""):
    """在重大操作之前調用"""
    
    # 1. 建立當前狀態快照
    state = self.snapshot_state(label)
    
    # 2. 放入撤銷棧
    self.undo_stack.append(state)
    
    # 3. 如果超過限制，刪除最舊的
    if len(self.undo_stack) > self._undo_limit:
        self.undo_stack.pop(0)
    
    # 4. 執行新操作時清空重做棧
    self.redo_stack.clear()
```

**調用時機**:
```python
# 操作前記錄撤銷點
self.push_undo_state("新增句")
success = self.renderer.data_processor.insert_dialogue_row(...)

# 操作後刷新 UI
if success:
    self.refresh_script_panel()
```

### 執行撤銷

```python
def undo_action(event=None):
    """Ctrl+Z 快捷鍵處理"""
    
    # 1. 檢查撤銷棧是否為空
    if not self.undo_stack:
        return "break"  # 沒有可撤銷的操作
    
    # 2. 當前狀態放入重做棧
    self.redo_stack.append(self.snapshot_state("redo"))
    
    # 3. 從撤銷棧取出上一個狀態
    state = self.undo_stack.pop()
    
    # 4. 復原到該狀態
    self.restore_state(state)
    
    # 5. 日誌輸出
    self.log(f"Undo: {state.get('label') or '回復上一個修改'}")
    
    return "break"  # 標記事件已處理
```

### 執行重做

```python
def redo_action(event=None):
    """Ctrl+Y 快捷鍵處理"""
    
    # 1. 檢查重做棧是否為空
    if not self.redo_stack:
        return "break"  # 沒有可重做的操作
    
    # 2. 當前狀態放入撤銷棧
    self.undo_stack.append(self.snapshot_state("undo"))
    
    # 3. 從重做棧取出下一個狀態
    state = self.redo_stack.pop()
    
    # 4. 復原到該狀態
    self.restore_state(state)
    
    # 5. 日誌輸出
    self.log(f"Redo: {state.get('label') or '重做修改'}")
    
    return "break"
```

## 狀態復原流程

### 復原方法

```python
def restore_state(state):
    """將應用還原到特定狀態"""
    
    dp = self.renderer.data_processor
    
    # ============ 1. 數據層復原 ============
    # 還原 DataFrame
    dp.df = None if state["df"] is None else state["df"].copy(deep=True)
    
    # 還原檔案路徑
    dp.path = state.get("df_path")
    
    # 清除緩存 (強制重新計算)
    if hasattr(dp, "invalidate_cache"):
        dp.invalidate_cache()
    
    # ============ 2. 播放器配置復原 ============
    # 還原裁剪範圍
    self.renderer.set_cut_ranges(state.get("cut_ranges", []))
    
    # 還原人物 ID 映射 (例: ID 1 → "Alice")
    self.renderer.yolo_id_to_speaker = dict(state.get("speakers", {}))
    
    # 還原人物樣式 (顏色、位置等)
    self.renderer.person_styles = {
        tid: dict(style) 
        for tid, style in state.get("person_styles", {}).items()
    }
    
    # 還原泡泡偏移
    self.renderer.bubble_offsets = dict(state.get("bubble_offsets", {}))
    
    # ============ 3. 選中狀態復原 ============
    self.selected_dialogue_row = state.get("selected_row")
    
    # ============ 4. 清除緩存並刷新 ============
    # 清空渲染緩存 (強制重新繪製)
    self.renderer.bubble_cache.clear()
    
    # 結束文本編輯撤銷組
    self.end_text_undo_group()
    
    # ============ 5. UI 刷新 ============
    self.refresh_after_state_restore()
```

### UI 刷新

```python
def refresh_after_state_restore():
    """復原後刷新所有界面元素"""
    
    # 1. 更新按鈕狀態
    self.btn_scan.configure(
        state="normal" if self.people_count_confirmed and self.renderer.data_processor.has_data() else "disabled"
    )
    
    # 2. 重新建構腳本面板
    self.refresh_script_panel()
    
    # 3. 更新時間軸和預覽
    if self.slider_timeline.cget("state") == "normal":
        frame = self.current_frame()
        
        # 同步欄位 (人物、發言人、文本)
        self.sync_fields_for_frame(frame)
        
        # 重新渲染預覽圖像
        self.refresh_current_preview()
        
        # 重新繪製波形 (句柄位置可能變化)
        self.draw_waveform(frame)
```

## 文本編輯撤銷組

### 問題

在文本欄位中每按一次鍵都記錄撤銷點會導致：
- 撤銷棧爆炸 (80 個限制快速填滿)
- 用戶體驗差 (需要 Undo 10 次才能回到編輯前)

### 解決方案

使用撤銷組機制，將連續的文本編輯視為一個操作：

```python
def begin_text_undo_group(event=None):
    """開始文本編輯會話"""
    
    if self.selected_dialogue_row is None:
        return
    
    # 記錄當前行號和原始文本
    self._typing_undo_row = self.selected_dialogue_row
    self._typing_undo_original = self.entry_text.get()
    
    # 标記: 已開始編輯，不要記錄每個鍵擊
    self._in_text_edit = True

def end_text_undo_group(event=None):
    """結束文本編輯會話，一次性記錄"""
    
    # 檢查文本是否真的變化了
    if self._typing_undo_original != self.entry_text.get():
        # 只在文本確實改變時才記錄撤銷點
        self.push_undo_state("編輯文本")
    
    # 清空編輯會話標記
    self._typing_undo_row = None
    self._typing_undo_original = None
    self._in_text_edit = False
```

### 事件綁定

```python
# 文本欄位綁定
entry_text.bind("<FocusIn>", self.begin_text_undo_group)
entry_text.bind("<FocusOut>", self.end_text_undo_group)
entry_text.bind("<KeyRelease>", self.on_text_changed)  # 實時更新預覽
```

**流程示例**:
```
用戶聚焦文本欄位
  ↓ FocusIn
開始文本撤銷組 (記錄原始文本)
  ↓
用戶輸入 "a", "b", "c", ...
  ↓ KeyRelease (每次)
實時更新預覽 (但不記錄撤銷點)
  ↓
用戶點擊其他位置或按 Tab
  ↓ FocusOut
結束文本撤銷組 (對比原始文本)
  ↓ 文本改變
記錄一個撤銷點
```

## 特定操作的撤銷標籤

不同操作使用不同的標籤以增強可讀性：

| 標籤 | 操作 | 按鍵/按鈕 |
|------|------|---------|
| `"新增句"` | 添加新對話 | `btn_add` |
| `"刪除句"` | 標記刪除 | `Delete` 鍵 |
| `"還原句"` | 還原已刪除 | `Delete` 鍵 |
| `"切斷句"` | 斷句 | `btn_split` |
| `"合併句"` | 合併對話 | `btn_merge` |
| `"修改說話者"` | 改發言人 | ComboBox |
| `"編輯文本"` | 修改文本 | Entry 失焦 |
| `"微調句子時間"` | 調整邊界 | `[` `]` 鍵 |

## 撤銷限制與記憶體管理

### 限制深度

```python
self._undo_limit = 80  # 預設 80 步

# 超過限制時自動刪除最舊的
if len(self.undo_stack) > self._undo_limit:
    self.undo_stack.pop(0)  # 刪除第一個 (最舊的)
```

**調整建議**:
- **低端設備**: 設為 30-50
- **標準設備**: 設為 80 (預設)
- **高端設備**: 設為 100-150

### 記憶體佔用

每個快照包含：
- DataFrame 副本: 依賴數據大小，通常 50KB - 2MB
- 配置字典: 數 KB

**估算**:
```
80 個快照 × 1MB 平均 = 80MB 最大記憶體佔用
```

大型影片 (4K、長片) 可能需要增加系統記憶體。

## 邊界情況處理

### 空棧處理

```python
def undo_action(event=None):
    if not self.undo_stack:
        return "break"  # 空棧時不做任何動作
        # 可選: messagebox.showinfo("提示", "沒有可撤銷的操作")
```

### 部分狀態恢復失敗

如果某個組件不存在或狀態格式不同：

```python
def restore_state(state):
    try:
        # ...復原邏輯...
    except Exception as e:
        self.log(f"恢復狀態時出錯: {e}")
        # 部分恢復完成，嘗試刷新 UI
        self.refresh_after_state_restore()
```

### 執行新操作時清空重做棧

```python
def push_undo_state(label=""):
    self.undo_stack.append(self.snapshot_state(label))
    self.redo_stack.clear()  # ← 重要！執行新操作後重做棧無效
```

**場景**:
```
撤銷 A, B           undo=[A], redo=[B, C]
執行新操作 D         undo=[A, D], redo=[]  ← 清空
```

用戶無法重做 B 和 C，因為分支了。

## 鍵盤快捷鍵

```python
# 在 __init__ 中綁定
self.bind_all("<Control-z>", self.undo_action)
self.bind_all("<Control-y>", self.redo_action)

# 或在編輯界面中
def on_key_event(event):
    if event.state & 0x0004:  # Ctrl 被按下
        if event.keysym == "z":
            return self.undo_action(event)
        elif event.keysym == "y":
            return self.redo_action(event)
```

### 平台差異

| 平台 | 撤銷 | 重做 |
|------|------|------|
| Windows | Ctrl+Z | Ctrl+Y |
| macOS | Cmd+Z | Cmd+Shift+Z 或 Cmd+Y |
| Linux | Ctrl+Z | Ctrl+Y |

目前實現支援 Windows/Linux，macOS 可能需要調整。

## 日誌記錄

### 日誌輸出

```python
self.log(f"Undo: {state.get('label')}")
self.log(f"Redo: {state.get('label')}")
```

### 日誌面板顯示

```
時間          操作
09:45:32      新增句
09:46:15      修改說話者
09:46:28      Undo: 修改說話者
09:46:30      Redo: 修改說話者
```

## 測試場景

### 基本撤銷重做

1. 新增句 A → Undo → Redo ✓
2. 修改 A 的文本 → Undo ✓
3. 修改 A 的發言人 → Undo ✓

### 複雜流程

1. 新增句 A, B, C
2. 刪除 B
3. 修改 A 的文本
4. Undo (恢復修改) → Undo (恢復刪除) → Undo (恢復新增)
5. 最終狀態應回到初始狀態

### 邊界情況

1. 棧滿後 (80 步) 繼續操作 → 最舊的應自動刪除
2. 在重做棧中執行新操作 → 重做棧應清空
3. 文本欄位快速編輯 (輸入 10 個字) → 應只記錄 1 個撤銷點

## 未來改進

1. **粒度控制**: 允許用戶選擇保存哪些操作
2. **可視化歷史**: UI 樹狀圖展示撤銷歷史
3. **自動保存**: 定期保存狀態快照到磁盤
4. **分支合併**: 支援多分支編輯歷史
5. **增量快照**: 只記錄變更部分而非完整狀態
