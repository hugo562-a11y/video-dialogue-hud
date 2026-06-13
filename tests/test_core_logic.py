import unittest

import pandas as pd

from core.constants import SILENCE_SPEAKER, SILENCE_TEXT
from core.data_processor import DataProcessor
from core.video_renderer import VideoRenderer
from ui.controls import ControlsMixin
from ui.editing import EditingMixin


class EditingHarness(EditingMixin):
    def __init__(self):
        self.renderer = VideoRenderer()
        self.renderer.data_processor.set_dataframe(
            pd.DataFrame(
                [
                    {"time": "00:00 - 00:01", "speaker": "A", "text": "hello"},
                    {"time": "00:02 - 00:03", "speaker": "B", "text": "world"},
                ]
            )
        )
        self.selected_dialogue_row = 0
        self.undo_labels = []
        self.refreshed_panel = False
        self.refreshed_preview = False
        self.logs = []

    def push_undo_state(self, label=""):
        self.undo_labels.append(label)

    def dialogue_indices(self):
        return list(self.renderer.data_processor.df.index)

    def refresh_script_panel(self):
        self.refreshed_panel = True

    def refresh_current_preview(self):
        self.refreshed_preview = True

    def log(self, text):
        self.logs.append(text)


class ControlsHarness(ControlsMixin):
    def __init__(self):
        self.renderer = VideoRenderer()
        self.renderer.fps = 10
        self.renderer.total_frames = 100
        self.renderer.data_processor.set_dataframe(
            pd.DataFrame(
                [
                    {"time": "00:01 - 00:03", "speaker": "A", "text": "one"},
                    {"time": "00:05 - 00:07", "speaker": "A", "text": "two"},
                ]
            )
        )

    def get_waveform_timeline_duration(self):
        return 10.0


class DataProcessorTests(unittest.TestCase):
    def make_processor(self):
        dp = DataProcessor()
        dp.set_dataframe(
            pd.DataFrame(
                [
                    {"time": "00:00 - 00:01", "speaker": "A", "text": "hello"},
                    {"time": "00:02 - 00:03", "speaker": "B", "text": "world"},
                ]
            )
        )
        return dp

    def test_dialogue_lookup_and_split(self):
        dp = self.make_processor()

        self.assertEqual(dp.get_columns(), ("time", "speaker", "text"))
        self.assertEqual(dp.find_dialogue_row(10, 30, 1, "A"), (0, "hello"))
        self.assertEqual(dp.find_dialogue_at_time(70, 30), (1, "world"))

        ok, _, new_idx = dp.split_dialogue_row(0, 2)
        self.assertTrue(ok)
        self.assertEqual(new_idx, 1)
        self.assertEqual(dp.df.loc[0, "text"], "he")
        self.assertEqual(dp.df.loc[1, "text"], "llo")

    def test_insert_delete_keeps_index_contiguous(self):
        dp = self.make_processor()

        new_idx = dp.insert_dialogue_row(1.2, 1.6, "A", "inserted")
        self.assertEqual(new_idx, 1)
        self.assertEqual(dp.df.loc[new_idx, "text"], "inserted")

        self.assertTrue(dp.delete_dialogue_row(new_idx))
        self.assertEqual(list(dp.df.index), [0, 1])
        self.assertEqual(dp.df.loc[1, "text"], "world")

    def test_split_can_preserve_existing_indices_for_incremental_ui(self):
        dp = self.make_processor()

        ok, _, new_idx = dp.split_dialogue_row(0, 2, reset_index=False)

        self.assertTrue(ok)
        self.assertEqual(new_idx, 2)
        self.assertEqual(list(dp.df.index), [0, 2, 1])
        self.assertEqual(dp.df.loc[0, "text"], "he")
        self.assertEqual(dp.df.loc[2, "text"], "llo")
        self.assertEqual(dp.df.loc[1, "text"], "world")

    def test_replace_speaker_updates_existing_rows(self):
        dp = self.make_processor()

        changed = dp.replace_speaker("A", "Alice")

        self.assertEqual(changed, 1)
        self.assertEqual(dp.df.loc[0, "speaker"], "Alice")
        self.assertEqual(dp.df.loc[1, "speaker"], "B")
        self.assertIn("Alice", dp.get_unique_speakers())

    def test_silence_rows_are_deleted_by_default(self):
        dp = DataProcessor()
        dp.set_dataframe(
            pd.DataFrame(
                [
                    {"time": "00:00 - 00:01", "speaker": SILENCE_SPEAKER, "text": SILENCE_TEXT},
                    {"time": "00:01 - 00:02", "speaker": "A", "text": "hello"},
                ]
            )
        )

        self.assertTrue(dp.is_deleted(0))
        self.assertFalse(dp.is_deleted(1))
        self.assertEqual(dp.get_deleted_time_ranges(), [(0.0, 1.0)])

    def test_export_cuts_outside_dialogue_but_keeps_restored_silence(self):
        dp = DataProcessor()
        dp.set_dataframe(
            pd.DataFrame(
                [
                    {"time": "00:01 - 00:02", "speaker": "A", "text": "hello"},
                    {"time": "00:02 - 00:03", "speaker": SILENCE_SPEAKER, "text": SILENCE_TEXT},
                    {"time": "00:04 - 00:05", "speaker": "B", "text": "world"},
                ]
            )
        )

        self.assertEqual(dp.get_export_cut_ranges(6), [(0.0, 1.0), (2.0, 4.0), (5.0, 6.0)])

        dp.set_deleted(1, False)

        self.assertEqual(dp.get_export_cut_ranges(6), [(0.0, 1.0), (3.0, 4.0), (5.0, 6.0)])

    def test_find_dialogue_row_edge_cases(self):
        dp = self.make_processor()

        self.assertEqual(dp.find_dialogue_row(0, 30, 1, ""), (0, "hello"))
        self.assertEqual(dp.find_dialogue_row(30, 30, 1, ""), (0, "hello"))
        self.assertEqual(dp.find_dialogue_row(31, 30, 1, ""), (None, ""))
        self.assertEqual(dp.find_dialogue_row(61, 30, 1, ""), (1, "world"))
        self.assertEqual(dp.find_dialogue_row(90, 30, 1, ""), (1, "world"))
        self.assertEqual(dp.find_dialogue_row(91, 30, 1, ""), (None, ""))

    def test_find_dialogue_row_manual_speaker_filter(self):
        dp = self.make_processor()

        self.assertEqual(dp.find_dialogue_row(10, 30, 1, "A"), (0, "hello"))
        self.assertEqual(dp.find_dialogue_row(10, 30, 1, "B"), (None, ""))
        self.assertEqual(dp.find_dialogue_row(70, 30, 1, "B"), (1, "world"))
        self.assertEqual(dp.find_dialogue_row(70, 30, 1, "A"), (None, ""))

    def test_find_dialogue_row_skips_deleted(self):
        dp = self.make_processor()
        dp.set_deleted(0)

        self.assertEqual(dp.find_dialogue_row(10, 30, 1, "A"), (None, ""))
        self.assertEqual(dp.find_dialogue_row(70, 30, 1, ""), (1, "world"))

    def test_find_dialogue_at_time(self):
        dp = self.make_processor()

        self.assertEqual(dp.find_dialogue_at_time(0, 30), (0, "hello"))
        self.assertEqual(dp.find_dialogue_at_time(30, 30), (0, "hello"))
        self.assertEqual(dp.find_dialogue_at_time(31, 30), (None, ""))
        self.assertEqual(dp.find_dialogue_at_time(61, 30), (1, "world"))
        self.assertEqual(dp.find_dialogue_at_time(90, 30), (1, "world"))
        self.assertEqual(dp.find_dialogue_at_time(91, 30), (None, ""))

    def test_merge_dialogue_rows(self):
        dp = self.make_processor()

        ok, msg = dp.merge_dialogue_rows(0)
        self.assertTrue(ok)
        self.assertEqual(dp.df.loc[0, "text"], "helloworld")
        self.assertEqual(len(dp.df), 1)

    def test_update_dialogue_fields(self):
        dp = self.make_processor()

        self.assertTrue(dp.update_dialogue_speaker(0, "Alice"))
        self.assertEqual(dp.df.loc[0, "speaker"], "Alice")

        self.assertTrue(dp.update_dialogue_time(0, 0.5, 1.5))
        time_col, _, _ = dp.get_columns()
        self.assertEqual(dp.df.loc[0, time_col], "00:00.50 - 00:01.50")

        self.assertTrue(dp.update_dialogue_row(0, "updated"))
        self.assertEqual(dp.df.loc[0, "text"], "updated")

    def test_remove_rows_overlapping_ranges(self):
        dp = self.make_processor()
        removed = dp.remove_rows_overlapping_ranges([(0.5, 1.5)])
        self.assertEqual(removed, 1)
        self.assertEqual(len(dp.df), 1)
        self.assertEqual(dp.df.loc[0, "text"], "world")

    def test_get_time_ranges(self):
        dp = self.make_processor()
        self.assertEqual(dp.get_kept_time_ranges(), [(0.0, 1.0), (2.0, 3.0)])
        self.assertEqual(dp.get_deleted_time_ranges(), [])

        dp.set_deleted(0)
        self.assertEqual(dp.get_kept_time_ranges(), [(2.0, 3.0)])
        self.assertEqual(dp.get_deleted_time_ranges(), [(0.0, 1.0)])

    def test_columns_cache_invalidated_on_df_change(self):
        dp = self.make_processor()
        cols1 = dp.get_columns()
        dp.set_dataframe(pd.DataFrame([{"時間": "0", "人物": "A", "內容": "hi"}]))
        cols2 = dp.get_columns()
        self.assertNotEqual(cols1, cols2)
        self.assertEqual(cols2, ("時間", "人物", "內容"))


class VideoRendererTests(unittest.TestCase):
    def setUp(self):
        self.r = VideoRenderer()

    def test_clear_bubble_cache_full(self):
        self.r.bubble_cache = {("a", "top", 1, "classic", "藍", 72, (255,)): "img1"}
        self.r.clear_bubble_cache()
        self.assertEqual(self.r.bubble_cache, {})

    def test_clear_bubble_cache_selective(self):
        self.r.bubble_cache = {
            ("a", "top", 1, "classic", "藍", 72, (255,)): "img1",
            ("b", "top", 2, "classic", "紅", 72, (255,)): "img2",
            ("c", "top", 1, "tech", "藍", 72, (255,)): "img3",
        }
        self.r.clear_bubble_cache(track_id=1)
        self.assertEqual(len(self.r.bubble_cache), 1)
        self.assertIn(2, [k[2] for k in self.r.bubble_cache])

    def test_text_for_track_returns_speaker_when_no_data(self):
        self.r.yolo_id_to_speaker = {1: "Alice"}
        self.assertEqual(self.r._text_for_track(1, 1), "Alice")

    def test_track_id_for_speaker(self):
        self.r.yolo_id_to_speaker = {1: "Alice", 2: "Bob"}
        self.assertEqual(self.r._track_id_for_speaker("Alice"), 1)
        self.assertEqual(self.r._track_id_for_speaker("Bob"), 2)
        self.assertEqual(self.r._track_id_for_speaker("Charlie"), 1)

    def test_wrap_text(self):
        text = "這是一段很長的對話內容測試"
        wrapped = self.r._wrap_text(text, limit=4)
        lines = wrapped.split("\n")
        self.assertTrue(all(len(l) <= 4 for l in lines))
        self.assertEqual("".join(lines), text)

    def test_default_bubble_color(self):
        name1 = self.r.default_bubble_color_name(1)
        name2 = self.r.default_bubble_color_name(2)
        self.assertIsInstance(name1, str)
        self.assertIsInstance(name2, str)
        self.assertNotEqual(name1, name2)

    def test_default_bubble_position(self):
        self.assertEqual(self.r.default_bubble_position(1), "top")
        self.assertEqual(self.r.default_bubble_position(2), "bottom")

    def test_pre_scan_dummy_box(self):
        box = self.r._pre_scan_dummy_box(1920, 1080, 2)
        self.assertEqual(box["id"], 2)
        x1, y1, x2, y2 = box["bbox"]
        self.assertGreater(x2, x1)
        self.assertGreater(y2, y1)


class EditingTests(unittest.TestCase):
    def test_delete_sentence_marks_row_for_export_cut(self):
        app = EditingHarness()

        result = app.delete_selected_dialogue()

        self.assertEqual(result, "break")
        self.assertTrue(app.renderer.data_processor.is_deleted(0))
        self.assertEqual(app.renderer.data_processor.get_deleted_time_ranges(), [(0.0, 1.0)])
        self.assertEqual(app.renderer.data_processor.find_dialogue_at_time(10, 30), (None, ""))
        self.assertEqual(len(app.renderer.data_processor.df), 2)
        self.assertEqual(app.undo_labels, ["刪除句"])
        self.assertTrue(app.refreshed_panel)
        self.assertTrue(app.refreshed_preview)

    def test_delete_sentence_toggles_restore(self):
        app = EditingHarness()

        app.delete_selected_dialogue()
        result = app.delete_selected_dialogue()

        self.assertEqual(result, "break")
        self.assertFalse(app.renderer.data_processor.is_deleted(0))
        self.assertEqual(app.renderer.data_processor.get_deleted_time_ranges(), [])
        self.assertEqual(app.undo_labels, ["刪除句", "還原句"])
        self.assertTrue(app.logs)


class ControlsPlaybackTests(unittest.TestCase):
    def test_edited_playback_plan_clips_from_current_time(self):
        app = ControlsHarness()

        plan = app._build_playback_plan(start_frame=21, play_edited=True)

        self.assertEqual(
            plan,
            [
                {"source_start": 2.0, "source_end": 3.0, "play_start": 0.0, "play_end": 1.0},
                {"source_start": 5.0, "source_end": 7.0, "play_start": 1.0, "play_end": 3.0},
            ],
        )

    def test_edited_playback_elapsed_maps_across_cut_gap(self):
        app = ControlsHarness()
        app._play_timeline_plan = app._build_playback_plan(start_frame=1, play_edited=True)

        self.assertAlmostEqual(app._source_seconds_for_play_elapsed(0.5), 1.5)
        self.assertAlmostEqual(app._source_seconds_for_play_elapsed(2.0), 5.0)
        self.assertAlmostEqual(app._source_seconds_for_play_elapsed(3.5), 6.5)


class RendererTests(unittest.TestCase):
    def test_cut_ranges_are_normalized(self):
        renderer = VideoRenderer()

        renderer.set_cut_ranges([(2.0, 3.0), (1.0, 2.02), (4.0, 4.01)])

        self.assertEqual(renderer.cut_ranges, [(1.0, 3.0)])
        self.assertTrue(renderer._frame_in_cut_ranges(31, 30))
        self.assertFalse(renderer._frame_in_cut_ranges(91, 30))

    def test_person_bubble_style_can_be_configured(self):
        renderer = VideoRenderer()

        renderer.set_person_bubble_style(1, "tech", "紅")

        self.assertEqual(renderer.get_person_bubble_style(1), {"style": "tech", "color": "紅", "position": "top"})
        self.assertEqual(renderer.get_person_bubble_style(2)["style"], "classic")
        renderer.set_person_bubble_style(2, "classic", "綠", "bottom")
        self.assertEqual(renderer.get_person_bubble_style(2)["position"], "bottom")

    def test_pre_scan_preview_uses_speaker_mapping_for_style_id(self):
        renderer = VideoRenderer()
        renderer.yolo_id_to_speaker = {1: "Alice", 2: "Bob"}
        renderer.set_person_bubble_style(2, "capsule", "綠", "bottom")

        self.assertEqual(renderer._track_id_for_speaker("Bob"), 2)
        box = renderer._pre_scan_dummy_box(1000, 600, 2)

        self.assertEqual(box["id"], 2)
        self.assertLess(box["bbox"][1], 150)

    def test_default_speaker_assignment_preserves_existing_names(self):
        renderer = VideoRenderer()
        renderer.yolo_id_to_speaker = {1: "Alice", 2: "Bob"}

        renderer._assign_default_speakers(2)

        self.assertEqual(renderer.yolo_id_to_speaker, {1: "Alice", 2: "Bob"})


if __name__ == "__main__":
    unittest.main()
