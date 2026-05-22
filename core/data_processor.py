"""DataProcessor — 負責對話腳本的載入、解析與編輯。"""
from __future__ import annotations

import os

import pandas as pd

from core.constants import SILENCE_SPEAKER, SILENCE_TEXT, MIN_SILENCE_SECONDS
from core.utils import (
    parse_time_range,
    format_time_range,
    frame_to_seconds,
    normalize_time_ranges,
    time_range_overlaps,
    find_column,
)

DELETED_COLUMN = "__deleted__"


class DataProcessor:
    def __init__(self):
        self.df: pd.DataFrame | None = None
        self.path: str | None = None
        self._dialogue_cache: list[dict] | None = None
        self._dialogue_cache_df_id: int | None = None

    def invalidate_cache(self) -> None:
        self._dialogue_cache = None
        self._dialogue_cache_df_id = None

    # ------------------------------------------------------------------ 載入
    def load_data(self, file_path: str) -> tuple[bool, str]:
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".csv":
                try:
                    self.df = pd.read_csv(file_path, encoding="utf-8-sig")
                except UnicodeDecodeError:
                    self.df = pd.read_csv(file_path, encoding="big5")
            elif ext in (".xls", ".xlsx"):
                self.df = pd.read_excel(file_path)
            else:
                return False, "只支援 CSV、XLS、XLSX 對話表。"
        except Exception as exc:
            return False, f"讀取失敗：{exc}"
        self.path = file_path
        self.invalidate_cache()
        self.ensure_internal_columns()
        return True, f"已載入 {len(self.df)} 筆對話：{os.path.basename(file_path)}"

    def set_dataframe(self, df: pd.DataFrame, source_name: str = "辨識腳本") -> tuple[bool, str]:
        self.df = df
        self.path = source_name
        self.invalidate_cache()
        self.ensure_internal_columns()
        return True, f"已套用 {len(self.df)} 筆對話：{source_name}"

    def ensure_internal_columns(self) -> None:
        if self.df is None:
            return
        created_deleted_column = DELETED_COLUMN not in self.df.columns
        if created_deleted_column:
            self.df[DELETED_COLUMN] = False
        self.df[DELETED_COLUMN] = self.df[DELETED_COLUMN].fillna(False).astype(bool)
        if created_deleted_column:
            self.mark_silence_rows_deleted()
        self.invalidate_cache()

    def mark_silence_rows_deleted(self) -> int:
        if self.df is None or self.df.empty:
            return 0
        _, speaker_col, _ = self.get_columns()
        if speaker_col is None:
            return 0
        values = self.df[speaker_col].fillna("").astype(str).str.strip()
        mask = values == SILENCE_SPEAKER
        if not mask.any():
            return 0
        self.df.loc[mask, DELETED_COLUMN] = True
        self.invalidate_cache()
        return int(mask.sum())

    def export_dataframe(self) -> pd.DataFrame:
        if self.df is None:
            return pd.DataFrame()
        return self.df.drop(columns=[DELETED_COLUMN], errors="ignore")

    # ------------------------------------------------------------------ 查詢
    def has_data(self) -> bool:
        return self.df is not None and not self.df.empty

    def is_deleted(self, row_idx) -> bool:
        if not self.has_data() or row_idx not in self.df.index or DELETED_COLUMN not in self.df.columns:
            return False
        return bool(self.df.at[row_idx, DELETED_COLUMN])

    def set_deleted(self, row_idx, deleted: bool = True) -> bool:
        if not self.has_data() or row_idx not in self.df.index:
            return False
        self.ensure_internal_columns()
        self.df.at[row_idx, DELETED_COLUMN] = bool(deleted)
        self.invalidate_cache()
        return True

    def get_deleted_time_ranges(self) -> list[tuple[float, float]]:
        if not self.has_data():
            return []
        time_col, _, _ = self.get_columns()
        if time_col is None:
            return []
        ranges = []
        for idx, row in self.df.iterrows():
            if not self.is_deleted(idx):
                continue
            start, end = parse_time_range(row[time_col])
            if start is not None and end is not None and end > start:
                ranges.append((start, end))
        return normalize_time_ranges(ranges)

    def get_kept_time_ranges(self) -> list[tuple[float, float]]:
        if not self.has_data():
            return []
        time_col, _, _ = self.get_columns()
        if time_col is None:
            return []
        ranges = []
        for idx, row in self.df.iterrows():
            if self.is_deleted(idx):
                continue
            start, end = parse_time_range(row[time_col])
            if start is not None and end is not None and end > start:
                ranges.append((start, end))
        return normalize_time_ranges(ranges)

    def get_export_cut_ranges(self, total_duration=None) -> list[tuple[float, float]]:
        """Cut everything that is not explicitly kept by an undeleted row."""
        kept_ranges = self.get_kept_time_ranges()
        if not kept_ranges:
            return self.get_deleted_time_ranges()

        duration = None
        if total_duration:
            try:
                duration = max(0.0, float(total_duration))
            except (TypeError, ValueError):
                duration = None

        cut_ranges = []
        cursor = 0.0
        for start, end in kept_ranges:
            start = max(0.0, float(start))
            end = max(start, float(end))
            if start > cursor:
                cut_ranges.append((cursor, start))
            cursor = max(cursor, end)
        if duration is not None and duration > cursor:
            cut_ranges.append((cursor, duration))
        return normalize_time_ranges(cut_ranges)

    def get_columns(self):
        if not self.has_data():
            return None, None, None
        time_col = find_column(self.df.columns, ["時間", "time", "start"])
        speaker_col = find_column(self.df.columns, ["說話者", "speaker", "人物", "角色", "id"])
        text_col = find_column(self.df.columns, ["對話", "內容", "文字", "text", "content"])
        return time_col, speaker_col, text_col

    def get_unique_speakers(self) -> list[str]:
        if not self.has_data():
            return []
        _, speaker_col, _ = self.get_columns()
        if speaker_col is None:
            return []
        values = self.df[speaker_col].dropna().astype(str).str.strip()
        if DELETED_COLUMN in self.df.columns:
            values = self.df.loc[~self.df[DELETED_COLUMN].astype(bool), speaker_col].dropna().astype(str).str.strip()
        return [v for v in values.unique().tolist() if v and v != SILENCE_SPEAKER]

    def _dialogue_rows(self) -> list[dict]:
        if not self.has_data():
            return []
        df_id = id(self.df)
        if self._dialogue_cache is not None and self._dialogue_cache_df_id == df_id:
            return self._dialogue_cache

        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or text_col is None:
            self._dialogue_cache = []
            self._dialogue_cache_df_id = df_id
            return []

        rows = []
        filled_times = self.df[time_col].ffill()
        for idx, row in self.df.iterrows():
            start, end = parse_time_range(filled_times.loc[idx])
            if start is None or end is None or end <= start:
                continue
            speaker = str(row[speaker_col]).strip() if speaker_col is not None else ""
            value = row[text_col]
            text = "" if pd.isna(value) else str(value).strip().strip("「」")
            rows.append({
                "idx": idx,
                "start": start,
                "end": end,
                "speaker": speaker,
                "text": text,
                "deleted": self.is_deleted(idx),
            })

        self._dialogue_cache = rows
        self._dialogue_cache_df_id = df_id
        return rows

    def get_dialogue(self, frame_idx: int, fps: float, total_frames: int, track_id: int, manual_speaker: str = "") -> str:
        if not self.has_data():
            return ""
        row_idx, text = self.find_dialogue_row(frame_idx, fps, track_id, manual_speaker)
        if row_idx is not None:
            return text
        return self.get_column_mapped_dialogue(frame_idx, total_frames, track_id)

    def find_dialogue_row(self, frame_idx: int, fps: float, track_id: int, manual_speaker: str = ""):
        time_sec = frame_to_seconds(frame_idx, fps)
        for row in self._dialogue_rows():
            if row["deleted"] or row["speaker"] == SILENCE_SPEAKER:
                continue
            if manual_speaker and row["speaker"] and row["speaker"] != manual_speaker:
                continue
            if row["start"] <= time_sec < row["end"]:
                return row["idx"], row["text"]
        return None, ""

    def find_dialogue_at_time(self, frame_idx: int, fps: float):
        if not self.has_data():
            return None, ""
        time_sec = frame_to_seconds(frame_idx, fps)
        for row in self._dialogue_rows():
            if row["deleted"] or row["speaker"] == SILENCE_SPEAKER:
                continue
            if row["start"] <= time_sec < row["end"]:
                return row["idx"], row["text"]
        return None, ""

    def get_dialogue_row_values(self, row_idx) -> tuple[str, str]:
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return "", ""
        _, speaker_col, text_col = self.get_columns()
        speaker = ""
        text = ""
        if speaker_col is not None:
            value = self.df.at[row_idx, speaker_col]
            speaker = "" if pd.isna(value) else str(value).strip()
        if text_col is not None:
            value = self.df.at[row_idx, text_col]
            text = "" if pd.isna(value) else str(value).strip().strip("「」")
        return speaker, text

    def get_column_mapped_dialogue(self, frame_idx: int, total_frames: int, track_id: int) -> str:
        if not self.has_data():
            return ""
        matched_col = None
        for col in self.df.columns:
            low = str(col).lower().replace(" ", "")
            if str(track_id) == str(col) or f"id{track_id}" in low or f"人物{track_id}" in low:
                matched_col = col
                break
        if matched_col is None:
            return ""
        data_len = len(self.df)
        if data_len == 0 or not total_frames:
            return ""
        row_pos = int(frame_idx / max(total_frames, 1) * data_len)
        row_pos = max(0, min(data_len - 1, row_pos))
        value = self.df.iloc[row_pos][matched_col]
        return "" if pd.isna(value) else str(value).strip()

    # ------------------------------------------------------------------ 靜默段
    def add_silence_rows(self, total_duration=None, min_silence: float = MIN_SILENCE_SECONDS) -> int:
        if not self.has_data():
            return 0
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            return 0

        speech_rows = []
        for _, row in self.df.iterrows():
            speaker = "" if pd.isna(row[speaker_col]) else str(row[speaker_col]).strip()
            if speaker == SILENCE_SPEAKER:
                continue
            start, end = parse_time_range(row[time_col])
            if start is None or end is None or end <= start:
                continue
            speech_rows.append((start, end, row.to_dict()))
        speech_rows.sort(key=lambda item: item[0])

        rows = []
        added = 0
        last_end = 0.0
        for start, end, row_dict in speech_rows:
            if start - last_end >= min_silence:
                rows.append(self._silence_row(time_col, speaker_col, text_col, last_end, start))
                added += 1
            rows.append(row_dict)
            last_end = max(last_end, end)
        if total_duration and total_duration - last_end >= min_silence:
            rows.append(self._silence_row(time_col, speaker_col, text_col, last_end, total_duration))
            added += 1
        if added:
            self.df = pd.DataFrame(rows, columns=list(self.df.columns))
            self.ensure_internal_columns()
            self.invalidate_cache()
        return added

    def _silence_row(self, time_col, speaker_col, text_col, start: float, end: float) -> dict:
        row = {col: "" for col in self.df.columns}
        row[time_col] = format_time_range(start, end)
        row[speaker_col] = SILENCE_SPEAKER
        row[text_col] = SILENCE_TEXT
        row[DELETED_COLUMN] = True
        return row

    def remove_rows_overlapping_ranges(self, ranges) -> int:
        if not self.has_data():
            return 0
        ranges = normalize_time_ranges(ranges)
        if not ranges:
            return 0
        time_col, _, _ = self.get_columns()
        if time_col is None:
            return 0
        kept_rows = []
        removed = 0
        for _, row in self.df.iterrows():
            start, end = parse_time_range(row[time_col])
            if time_range_overlaps(start, end, ranges):
                removed += 1
                continue
            kept_rows.append(row.to_dict())
        if removed:
            self.df = pd.DataFrame(kept_rows, columns=list(self.df.columns))
            self.ensure_internal_columns()
            self.invalidate_cache()
        return removed

    # ------------------------------------------------------------------ 修改
    def update_dialogue_row(self, row_idx, text: str) -> bool:
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False
        _, _, text_col = self.get_columns()
        if text_col is None:
            return False
        self.df.at[row_idx, text_col] = text
        self.invalidate_cache()
        return True

    def update_dialogue_speaker(self, row_idx, speaker: str) -> bool:
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False
        _, speaker_col, _ = self.get_columns()
        if speaker_col is None:
            return False
        speaker = str(speaker).strip()
        if not speaker:
            return False
        self.df.at[row_idx, speaker_col] = speaker
        self.invalidate_cache()
        return True

    def replace_speaker(self, old_speaker: str, new_speaker: str) -> int:
        if not self.has_data():
            return 0
        _, speaker_col, _ = self.get_columns()
        if speaker_col is None:
            return 0
        old_speaker = str(old_speaker).strip()
        new_speaker = str(new_speaker).strip()
        if not old_speaker or not new_speaker or old_speaker == new_speaker:
            return 0
        values = self.df[speaker_col].fillna("").astype(str).str.strip()
        mask = values == old_speaker
        if not mask.any():
            return 0
        self.df.loc[mask, speaker_col] = new_speaker
        self.invalidate_cache()
        return int(mask.sum())

    def update_dialogue_time(self, row_idx, start: float, end: float, min_duration: float = 0.05) -> bool:
        if not self.has_data() or row_idx is None or row_idx not in self.df.index:
            return False
        time_col, _, _ = self.get_columns()
        if time_col is None:
            return False
        start = max(0.0, float(start))
        end = max(0.0, float(end))
        if end - start < min_duration:
            return False
        self.df.at[row_idx, time_col] = format_time_range(start, end)
        self.invalidate_cache()
        return True

    # ------------------------------------------------------------------ 結構操作
    def split_dialogue_row(self, row_idx, cursor_pos: int) -> tuple[bool, str, int | None]:
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or text_col is None:
            return False, "腳本格式不完整，無法斷句。", None
        if row_idx not in self.df.index:
            return False, "找不到要斷的列。", None
        old_text = "" if pd.isna(self.df.at[row_idx, text_col]) else str(self.df.at[row_idx, text_col])
        cursor_pos = max(1, min(int(cursor_pos), len(old_text) - 1))
        left_text = old_text[:cursor_pos].strip()
        right_text = old_text[cursor_pos:].strip()
        if not left_text or not right_text:
            return False, "請把游標放在句子中間再斷句。", None
        start, end = parse_time_range(self.df.at[row_idx, time_col])
        if start is None or end is None or end <= start:
            return False, "這列時間格式無法斷句。", None
        ratio = len(left_text) / max(1, len(left_text) + len(right_text))
        split_at = max(start + 0.05, min(end - 0.05, start + (end - start) * ratio))

        columns = list(self.df.columns)
        row_data = self.df.loc[row_idx].to_dict()
        first = dict(row_data)
        second = dict(row_data)
        first[time_col] = format_time_range(start, split_at)
        first[text_col] = left_text
        second[time_col] = format_time_range(split_at, end)
        second[text_col] = right_text

        rows = []
        new_second_idx = None
        for idx, row in self.df.iterrows():
            if idx == row_idx:
                rows.append(first)
                rows.append(second)
                new_second_idx = len(rows) - 1
            else:
                rows.append(row.to_dict())
        # reset_index 確保索引連續，避免後續混用 positional / label index
        self.df = pd.DataFrame(rows, columns=columns).reset_index(drop=True)
        self.ensure_internal_columns()
        self.invalidate_cache()
        return True, "已斷成兩句。", new_second_idx

    def insert_dialogue_row(self, start: float, end: float, speaker: str, text: str):
        if not self.has_data():
            self.df = pd.DataFrame(columns=["時間點", "說話者", "對話內容"])
            self.invalidate_cache()
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or speaker_col is None or text_col is None:
            time_col, speaker_col, text_col = "時間點", "說話者", "對話內容"
            self.df = pd.DataFrame(columns=[time_col, speaker_col, text_col])
            self.invalidate_cache()

        new_row = {col: "" for col in self.df.columns}
        new_row[time_col] = format_time_range(start, end)
        new_row[speaker_col] = speaker or "人物 1"
        new_row[text_col] = text
        marker = "__new_dialogue_row__"
        new_row[marker] = True
        rows = [row.to_dict() for _, row in self.df.iterrows()]
        rows.append(new_row)
        rows.sort(key=lambda row: parse_time_range(row.get(time_col, ""))[0] or 0)
        self.df = pd.DataFrame(rows)
        new_idx = next((idx for idx, row in self.df.iterrows() if bool(row.get(marker, False))), len(rows) - 1)
        if marker in self.df.columns:
            self.df = self.df.drop(columns=[marker])
        orig_cols = [c for c in self.df.columns if c in list(new_row.keys()) and c != marker]
        self.df = self.df[orig_cols]
        # reset_index 確保索引連續
        self.df = self.df.reset_index(drop=True)
        # new_idx 可能因 reset 後仍正確（DataFrame 是新建的），但重新找一次更安全
        # 用時間比對找回新行
        from core.utils import parse_time_range as _ptr
        target_time = format_time_range(start, end)
        candidates = self.df.index[self.df[time_col] == target_time].tolist()
        if candidates:
            new_idx = candidates[-1]
        self.ensure_internal_columns()
        self.invalidate_cache()
        return new_idx

    def delete_dialogue_row(self, row_idx) -> bool:
        if not self.has_data() or row_idx not in self.df.index:
            return False
        self.df = self.df.drop(index=row_idx).reset_index(drop=True)
        self.ensure_internal_columns()
        self.invalidate_cache()
        return True

    def merge_dialogue_rows(self, row_idx) -> tuple[bool, str]:
        if not self.has_data() or row_idx not in self.df.index:
            return False, "找不到要合併的列。"
        pos = list(self.df.index).index(row_idx)
        if pos >= len(self.df) - 1:
            return False, "最後一列沒有下一句可合併。"
        next_idx = self.df.index[pos + 1]
        time_col, speaker_col, text_col = self.get_columns()
        if time_col is None or text_col is None:
            return False, "腳本格式不完整，無法合併。"
        start, _ = parse_time_range(self.df.at[row_idx, time_col])
        _, end = parse_time_range(self.df.at[next_idx, time_col])
        if start is None or end is None:
            return False, "時間格式無法合併。"
        text1 = "" if pd.isna(self.df.at[row_idx, text_col]) else str(self.df.at[row_idx, text_col]).strip()
        text2 = "" if pd.isna(self.df.at[next_idx, text_col]) else str(self.df.at[next_idx, text_col]).strip()
        self.df.at[row_idx, time_col] = format_time_range(start, end)
        if text1 == SILENCE_TEXT:
            merged_text = text2
        elif text2 == SILENCE_TEXT:
            merged_text = text1
        else:
            merged_text = text1 + text2
        self.df.at[row_idx, text_col] = merged_text
        self.df = self.df.drop(index=next_idx).reset_index(drop=True)
        self.ensure_internal_columns()
        self.invalidate_cache()
        return True, "已合併下一句。"
