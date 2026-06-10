# SKILL: 腳本面板字句顯示與視覺化

## 概述

腳本面板的字句顯示系統負責動態渲染對話內容、管理視覺樣式、以及處理不同狀態下的顯示邏輯。

## 行狀態分類

### 狀態判定

```python
# 每行計算以下狀態
is_selected = row_idx == self.selected_dialogue_row    # 被選中
is_silence = speaker == SILENCE_SPEAKER                 # 無講話
is_deleted = dp.is_deleted(row_idx)                     # 已刪除
```

### 狀態優先級

| 優先級 | 狀態 | 背景色 | 邊框 |
|--------|------|--------|------|
| 1 (高) | 已刪除 + 選中 | `#4A2630` (暗紅) | 黃金色 |
| 2 | 已刪除 + 未選中 | `#4A2630` | 無 |
| 3 | 已選中 | `#28364A` (亮藍) | 黃金色 |
| 4 | 無講話 | `#252A34` (灰色) | 無 |
| 5 (低) | 普通 | 根據發言人調色盤 | 無 |

## 行背景與邊框

### 背景色選擇邏輯

```python
# 首先判斷是否刪除
if is_deleted:
    bg = "#4A2630"  # 暗紅，表示該行已標記為刪除
elif is_selected:
    bg = "#28364A"  # 亮藍，表示當前選中
elif is_silence:
    bg = "#252A34"  # 中性灰，表示無講話
else:
    # 根據發言人取得調色盤顏色
    speaker_bg, speaker_accent = self.speaker_palette(speaker, row_idx)
    bg = speaker_bg
```

### 邊框樣式

```python
border_width = 1 if is_selected else 0
border_color = "#FBBF24" if is_selected else speaker_accent

line = ctk.CTkFrame(
    self.script_scroll, 
    fg_color=bg,
    border_width=border_width, 
    border_color=border_color,
)
```

**邊框設計**:
- **選中時**: 1px 黃金色邊框 (`#FBBF24`)
- **未選中**: 無邊框，但背景色本身即可區分

## 字體與文本樣式

### 字體定義

```python
# 正常字體
normal_font = ctk.CTkFont(
    family="Microsoft JhengHei UI", 
    size=12
)

# 刪除線字體 (用於已刪除的行)
strike_font = ctk.CTkFont(
    family="Microsoft JhengHei UI", 
    size=12, 
    overstrike=True
)

# 小號刪除線字體 (用於壓縮的無講話行)
small_strike_font = ctk.CTkFont(
    family="Microsoft JhengHei UI", 
    size=11, 
    overstrike=True
)
```

### 文本顏色

```python
# 根據刪除狀態設定文本顏色
text_color = "#8A93A6" if is_deleted else None  # None = 使用默認色

# 已刪除的行使用灰色文本加刪除線
ctk.CTkLabel(
    line, 
    text=text,
    text_color=text_color,
    font=strike_font if is_deleted else normal_font,
)
```

## 時間按鈕 (Time Display & Button)

### 按鈕配置

```python
time_btn = ctk.CTkButton(
    line, 
    text=time_text or "--:--",
    width=98,                          # 固定寬度
    height=26 if is_silence else 28,   # 無講話行較矮
    fg_color="#5B2B34" if is_deleted else "#334155",
    hover_color="#73323E" if is_deleted else "#475569",
    command=lambda idx=row_idx: self.select_dialogue_row(idx, seek=True),
)
time_btn.grid(
    row=0, 
    column=0, 
    padx=(6, 4), 
    pady=(4 if is_silence else 6, 2 if is_silence else 2), 
    sticky="w"
)
```

### 時間格式化

```python
# 時間來自 CSV，需要解析並格式化
time_text = str(row[time_col]).strip()  # 例: "0:30 - 0:45"

def format_timecode(seconds):
    """將秒數轉換為 MM:SS 格式"""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"
    # 例: 30.5 秒 → "0:30"
```

### 時間範圍顯示

CSV 中的時間格式通常為:
```
時間欄位: "0:30 - 0:45"
          └─ 句首  └─ 句尾

按鈕顯示: "0:30"  (只顯示句首)
完整資訊: 在波形區域顯示句首和句尾的句柄
```

### 懸停效果

- **正常顏色**: `#334155`
- **懸停顏色**: `#475569` (變亮)
- **刪除狀態**: `#5B2B34` → `#73323E`

### 點擊行為

```python
def select_dialogue_row(row_idx, seek=False):
    """點擊時間按鈕"""
    self.selected_dialogue_row = row_idx
    
    if seek:
        # 跳轉到該對話的開始時間
        start_time, _ = parse_time_range(get_dialogue_time(row_idx))
        frame = seconds_to_frame(start_time, fps)
        self.slider_timeline.set(frame)
        
        # 觸發預覽更新
        self.refresh_current_preview()
```

## 發言人欄位 (Speaker ComboBox)

### 組件結構

```python
# 發言人下拉選單
combo_speaker = ctk.CTkComboBox(
    line,
    values=speakers,  # 所有已知人物列表
    variable=tk.StringVar(value=speaker),
    height=28,
    text_color=text_color if is_deleted else None,
    state="readonly" if is_deleted else "normal",
)
```

### 功能特性

1. **預設選項**: 顯示當前發言人
2. **下拉菜單**: 列出所有已知人物
3. **自由輸入**: 可直接輸入新人物名稱
4. **自動保存**: 失焦時自動更新數據層
5. **刪除狀態**: 禁用編輯 (readonly)

### 人物清單來源

```python
def get_person_speaker_options():
    """收集所有人物選項"""
    speakers = set()
    
    # 從現有對話收集
    for speaker in self.renderer.data_processor.get_all_speakers():
        speakers.add(speaker)
    
    # 從 YOLO ID 映射收集
    for tid, speaker in self.renderer.yolo_id_to_speaker.items():
        speakers.add(speaker)
    
    return sorted(list(speakers))
```

### 變更事件處理

```python
def on_speaker_change(value):
    """發言人選項變更時"""
    row_idx = current_row
    
    # 記錄撤銷點
    self.push_undo_state("修改說話者")
    
    # 更新數據層
    self.renderer.data_processor.update_dialogue_speaker(row_idx, value)
    
    # 同步 YOLO ID 映射
    tid = get_current_person_id()
    self.renderer.yolo_id_to_speaker[tid] = value
    
    # 刷新預覽 (顏色變更)
    self.renderer.bubble_cache.clear()
    self.refresh_current_preview()
```

## 對話文本欄位 (Text Entry)

### 組件配置

```python
entry_text = ctk.CTkEntry(
    line,
    height=28,
    text_color=text_color if is_deleted else None,
    state="readonly" if is_deleted else "normal",
    border_color=speaker_accent,
)
entry_text.insert(0, text)
```

### 文本編輯事件

```python
# 獲得焦點時開始撤銷組
entry_text.bind("<FocusIn>", lambda e: self.begin_text_undo_group())

# 文本變更時即時更新
entry_text.bind("<KeyRelease>", lambda e: self.update_dialogue_text(row_idx))

# 失焦時結束撤銷組
entry_text.bind("<FocusOut>", lambda e: self.end_text_undo_group())
```

### 刪除線顯示 (Deleted Rows)

```python
# 已刪除的行使用刪除線字體顯示
if is_deleted:
    label_text = ctk.CTkLabel(
        line,
        text=text or speaker,
        font=small_strike_font,
        text_color="#8A93A6",
    )
    label_text.grid(...)
else:
    entry_text = ctk.CTkEntry(
        line,
        ...,
    )
    entry_text.grid(...)
```

## 操作按鈕區

### 刪除/還原按鈕

#### 已刪除狀態

```python
btn_restore = ctk.CTkButton(
    line,
    text="還",          # 「還原」的簡稱
    width=28,
    height=28,
    fg_color="#2E5B8B",      # 藍色
    hover_color="#3572A5",   # 亮藍
    command=lambda idx=row_idx: self.restore_dialogue_from_panel(idx),
)
btn_restore.grid(row=0, column=3, padx=2, pady=6, sticky="e")
```

#### 未刪除狀態

```python
btn_delete = ctk.CTkButton(
    line,
    text="刪",          # 「刪除」的簡稱
    width=28,
    height=28,
    fg_color="#5B2B34",      # 暗紅色
    hover_color="#7B3B4C",   # 亮紅
    command=lambda idx=row_idx: self.delete_selected_dialogue_panel(idx),
)
btn_delete.grid(row=0, column=3, padx=2, pady=6, sticky="e")
```

### 新增按鈕 (行尾)

```python
btn_add_after = ctk.CTkButton(
    line,
    text="➕",
    width=28,
    height=28,
    fg_color="#2E5B3E",      # 深綠色
    hover_color="#3F8B55",   # 亮綠
    command=lambda idx=row_idx: self.insert_dialogue_after_panel(idx),
)
btn_add_after.grid(row=0, column=4, padx=2, pady=6, sticky="e")
```

## 特殊行類型

### 無講話行 (Silence Rows)

**特徵**:
- 發言人為 `SILENCE_SPEAKER` (預設: 「無講話」)
- 高度較矮: 26px (vs 普通 28px)
- 背景色固定: `#252A34`
- 不顯示文本輸入框

**顯示內容**:
```
[時間按鈕] [發言人標籤] [🔇圖示] [刪/還] [➕]
  0:30     無講話
```

```python
if is_silence:
    # 不創建 entry_text，改用 label
    label_speaker = ctk.CTkLabel(
        line,
        text=speaker or "未命名",
        text_color=text_color,
        anchor="w",
        font=normal_font,
    )
    label_speaker.grid(row=0, column=1, padx=4, pady=6, sticky="ew")
```

### 已刪除行 (Deleted Rows)

**特徵**:
- 背景色: `#4A2630` (暗紅)
- 文本: 灰色 `#8A93A6` + 刪除線
- 按鈕: 「還原」(藍色)

**顯示範例**:
```
[時間] ~~發言人~~ ~~文本~~ [還] [➕]
 0:30
```

```python
if is_deleted:
    ctk.CTkLabel(
        line, 
        text=speaker or "未命名",
        text_color="#8A93A6", 
        anchor="w",
        font=small_strike_font,
    ).grid(...)
    
    ctk.CTkLabel(
        line, 
        text=text,
        text_color="#8A93A6", 
        font=strike_font,
    ).grid(...)
```

## 選中狀態視覺化

### 選中行特徵

```python
if is_selected:
    line = ctk.CTkFrame(
        self.script_scroll,
        fg_color="#28364A",      # 亮藍背景
        border_width=1,
        border_color="#FBBF24",  # 黃金色邊框
    )
```

**視覺指示**:
- 背景色變為亮藍 (`#28364A`)
- 加 1px 黃金色邊框 (`#FBBF24`)
- 所有文本和按鈕變為白色/亮色

### 自動滾動到視圖

```python
def select_dialogue_row(row_idx, seek=False):
    self.selected_dialogue_row = row_idx
    
    # 計算目標行的位置
    row_position = calculate_row_position(row_idx)
    
    # 平滑滾動到可見範圍
    self.script_scroll.yview_moveto(row_position)
```

## 行寬度與佈局 (Grid Layout)

```python
line.grid_columnconfigure(0, weight=0)  # 時間按鈕: 固定寬度 (98px)
line.grid_columnconfigure(1, weight=1)  # 發言人/文本: 伸縮
line.grid_columnconfigure(2, weight=0)  # 操作按鈕: 固定寬度 (28px×2)
line.grid_columnconfigure(3, weight=0)
line.grid_columnconfigure(4, weight=0)
```

### 按鈕佈局

```
Row 0:
┌─────┬──────────┬──────┬────┬────┐
│時間 │發言人/文本│ 空間 │刪/還│ ➕ │
└─────┴──────────┴──────┴────┴────┘
   98px  伸縮    ...   28px 28px
```

## 行邊距與間距

```python
# 行容器邊距
line.pack(
    fill="x", 
    padx=4,                            # 左右邊距 4px
    pady=(1 if is_silence else 3),     # 上下邊距: 無講話 1px，普通 3px
)

# 時間按鈕
time_btn.grid(
    row=0, 
    column=0, 
    padx=(6, 4),                       # 左 6px，右 4px
    pady=(4 if is_silence else 6, 2),  # 上邊距，下邊距 2px
    sticky="w"
)

# 發言人
speaker_field.grid(
    row=0, 
    column=1, 
    padx=4,
    pady=(6, 2),
    sticky="ew"
)

# 操作按鈕
btn_delete.grid(
    row=0, 
    column=3, 
    padx=2,
    pady=6,
    sticky="e"
)
```

## 性能最佳化

### UI 組件快取

```python
# 儲存行的 UI 組件引用，以供後續更新
script_row_widgets[row_idx] = {
    'frame': line,
    'time_btn': time_btn,
    'speaker': combo_speaker,
    'text': entry_text,
    'delete_btn': btn_delete,
}
```

### 增量更新

```python
def update_script_row_deleted_state(row_idx):
    """只更新行的刪除狀態，不重建整行"""
    
    if row_idx not in script_row_widgets:
        return False
    
    widgets = script_row_widgets[row_idx]
    is_deleted = dp.is_deleted(row_idx)
    
    # 更新背景色
    widgets['frame'].configure(
        fg_color="#4A2630" if is_deleted else original_color
    )
    
    # 更新文本樣式
    widgets['speaker'].configure(
        text_color="#8A93A6" if is_deleted else None
    )
    
    # 交換刪除/還原按鈕
    # ...
    
    return True
```

### 虛擬滾動 (Future Enhancement)

對於非常大的腳本 (1000+ 行)，可考慮：
- 只為可見行創建 UI 組件
- 使用 Canvas 虛擬滾動
- 按需加載和卸載組件
