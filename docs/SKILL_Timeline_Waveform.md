# SKILL: 時間軸與波形功能

## 概述

時間軸功能是工具的核心，提供了音頻波形視覺化、時間範圍調整、平移縮放等互動功能，用於精確編輯影片中的對話時間。

## 波形生成流程

### 音頻提取
```
影片文件 → FFmpeg → WAV 文件 → 音頻採樣 → 波形峰值
```

### 參數設定
- **音頻格式**: PCM 16-bit mono
- **採樣率**: 16,000 Hz (16kHz)
- **時間步**: 0.01 秒 (10ms 分辨率)
- **處理**: 每 10ms 計算一個峰值

### 峰值計算
1. 音頻分割成 0.01 秒的塊
2. 計算每塊的最大絕對值 (峰值)
3. 正規化到 0-1 範圍
4. 儲存為浮點數組

### 活動檢測

```python
def _activity_intervals_from_levels(levels, step_seconds, 
                                   min_active=0.08, bridge_gap=0.14):
    # 計算閾值 = max(floor × 2.2, peak × 0.18, 0.035)
    # floor = 35 百分位，peak = 95 百分位
    
    # 辨識活動區間 (連續超過閾值的部分)
    # 合併距離 < 0.14 秒的間隙 (搭橋效果)
    
    return [(start_sec, end_sec), ...]  # 活動區間列表
```

**參數詳解**:
- `min_active` (0.08): 檢測到音頻的最小強度閾值比例
- `bridge_gap` (0.14): 自動合併相近活動區間的最大間隙 (秒)

## 波形顯示與交互

### 波形繪製

#### 視圖範圍
- `waveform_view_start`: 顯示開始時間 (秒)
- `waveform_view_end`: 顯示結束時間 (秒)
- 若為 None，則顯示整個影片時長

#### 繪製區域
- **背景**: 深色，網格線標示秒數
- **波形線**: 藍色折線，代表音頻強度
- **活動區間**: 綠色高亮區域
- **當前播放位置**: 紅色豎線標記

#### 文字標籤
- **時間標籤**: 顯示秒數 (0, 10, 20, ...)
- **持續時間**: 顯示選中區間的總時長

### 滾動縮放

#### 滾輪操作
- **向上滾輪**: 放大波形 (增加細節)
- **向下滾輪**: 縮小波形 (查看更廣範圍)
- **縮放限制**: 最小 0.1x，最大 10x

#### 平移 (拖曳)
- **模式**: 按住 Alt 鍵 + 拖曳
- **方向**: 水平平移以改變視窗起始位置
- **記錄**: 儲存平移起點和原始時間範圍

```python
# 平移計算
delta_pixels = current_x - _waveform_pan_start_x
pixels_per_second = (canvas_width / view_duration)
time_delta = delta_pixels / pixels_per_second

new_view_start = _waveform_pan_start_range[0] - time_delta
new_view_end = _waveform_pan_start_range[1] - time_delta
```

### 滾動顯示比例 (Zoom Level)

#### 比例顯示
- **當前縮放級別**: 顯示在波形區域右上角
- **格式**: 「1.5x」、「0.8x」 等

#### 自適應顯示
- **自動調整**: 根據視頻時長自動計算合適的初始縮放
- **最佳視圖**: 使整個視頻在一屏內顯示
- **細節模式**: 可放大到單個音頻幀

## 時間軸句柄與邊界調整

### 對話時間範圍

#### 對話物件結構
```python
# CSV 中的時間欄位格式: "開始時間 - 結束時間"
# 例如: "0:30 - 0:45" 或 "30.5 - 45.2"
```

#### 句首句尾設定

##### 句首調整 (Start Time)
- **操作**: 按住並拖曳左側句柄
- **約束**: 不能超過句尾，最小間隔 0.05 秒
- **快捷鍵**: `[` 鍵前進 0.05 秒，`Shift+[` 後退 0.05 秒

##### 句尾調整 (End Time)
- **操作**: 按住並拖曳右側句柄
- **約束**: 不能低於句首，最小間隔 0.05 秒
- **快捷鍵**: `]` 鍵前進 0.05 秒，`Shift+]` 後退 0.05 秒

### 視覺反饋

#### 句柄設計
- **外觀**: 小圓形或三角形標記
- **顏色**: 根據發言人顏色
- **懸停**: 變亮表示可拖曳
- **拖曳中**: 實時更新時間顯示

#### 時間顯示
- **起始時刻**: 「0:30」(分:秒 格式)
- **結束時刻**: 「0:45」
- **總長度**: 「15s」或「00:15」

### 平移範圍 (Pan Range)

#### 邊界檢查
```python
# 調整時間時的邊界檢查
if edge == "start":
    start = max(0.0, min(end - 0.05, start + delta))
else:
    end = max(start + 0.05, end + delta)
```

#### 容許範圍
- **最小值**: 0 秒 (不能為負)
- **最大值**: 影片總時長
- **最小間隔**: 0.05 秒 (50 毫秒)

## 波形句柄管理

### 句柄列表

```python
# 儲存結構
waveform_dialogue_handles = [
    {
        'row_idx': 0,           # 對應的 DataFrame 行編號
        'start_x': 100.0,       # 句首在 canvas 上的 x 座標
        'end_x': 200.0,         # 句尾在 canvas 上的 x 座標
        'speaker': 'Alice',     # 發言人
        'color': '#38BDF8',     # 顏色
    },
    ...
]
```

### 句柄交互

#### 拖曳檢測
- **滑鼠移動**: 檢查是否在句柄附近 (±10px 範圍)
- **滑鼠按下**: 記錄拖曳模式和起始位置
- **滑鼠移動**: 即時計算新時間並更新界面
- **滑鼠釋放**: 提交變更到數據層

#### 拖曳模式識別
```python
_waveform_drag_mode = None  # 待機狀態
_waveform_drag_mode = 'start'  # 拖曳句首
_waveform_drag_mode = 'end'    # 拖曳句尾
_waveform_drag_mode = 'range'  # 移動整個區間
```

## 波形區域交互總結

| 操作 | 組合鍵 | 效果 |
|------|-------|------|
| 滾輪上 | 無 | 放大波形 (細節化) |
| 滾輪下 | 無 | 縮小波形 (概覽化) |
| 拖曳 | Alt | 平移波形視圖 |
| 拖曳句首 | 無 | 調整對話開始時間 |
| 拖曳句尾 | 無 | 調整對話結束時間 |
| 拖曳區間 | Ctrl | 移動整個對話區間 |
| 按鍵 `[` | 無 | 句首後退 50ms |
| 按鍵 `]` | 無 | 句尾前進 50ms |
| 按鍵 `[` | Shift | 句首前進 50ms |
| 按鍵 `]` | Shift | 句尾後退 50ms |
| 點擊句柄 | 雙擊 | 精確輸入時間值 |

## 時間轉換工具

### 幀與時間互換

```python
# 幀 → 秒
seconds = frame_to_seconds(frame_idx, fps)
# 例: 幀 30 @ 30fps = 1.0 秒

# 秒 → 幀
frame_idx = seconds_to_frame(seconds, fps)
# 例: 1.0 秒 @ 30fps = 幀 30
```

### 時間字符串解析

```python
def parse_time_seconds(value: str) -> float | None:
    """解析多種時間格式"""
    # 支援格式:
    # "30.5"     → 30.5 秒
    # "0:30"     → 30 秒 (分:秒)
    # "1:30:45"  → 5445 秒 (時:分:秒)
    # "30 - 45"  → 30 秒 (使用 '-' 分隔符時取前半部分)
```

### 時間範圍解析

```python
def parse_time_range(value: str) -> tuple[float, float]:
    """解析時間範圍"""
    # "0:30 - 0:45" → (30.0, 45.0)
    # "30 - 45"     → (30.0, 45.0)
    # "0:30"        → (30.0, None)
```

## 波形緩存與效能

### 緩存機制
- **waveform_samples**: 音頻峰值快取
- **waveform_activity_intervals**: 活動區間快取
- **waveform_duration**: 影片時長快取
- **_waveform_audio_path**: 暫時 WAV 檔案路徑

### 清理操作
```python
def _clear_waveform_audio_cache():
    # 刪除暫時的 WAV 文件
    # 清空 samples 和 duration
    # 重置視圖範圍
```

## 實時更新流程

### 波形更新觸發
1. 選擇新影片 → 重新生成波形
2. 時間軸滑桿移動 → 更新紅線位置
3. 改變發言人顏色 → 重繪句柄
4. 編輯對話時間 → 更新句柄位置
5. 刪除/還原對話 → 重繪波形

### 隊列驅動更新
```python
# 波形生成在後台線程完成
ui_queue.put({
    'type': 'waveform',
    'samples': peaks,
    'duration': duration,
    'step_seconds': 0.01,
    'activity_intervals': intervals,
    'audio_path': wav_path
})

# 主線程定期檢查隊列
def check_queue():
    while not ui_queue.empty():
        msg = ui_queue.get()
        if msg['type'] == 'waveform':
            self.load_waveform_data(msg)
```
