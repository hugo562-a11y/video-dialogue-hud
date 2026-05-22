import unittest

import pandas as pd

from core.constants import SILENCE_SPEAKER, SILENCE_TEXT
from core.data_processor import DataProcessor
from core.video_renderer import VideoRenderer
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
