import unittest

import pandas as pd

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


class EditingTests(unittest.TestCase):
    def test_delete_sentence_does_not_cut_video_range(self):
        app = EditingHarness()

        result = app.delete_selected_dialogue()

        self.assertEqual(result, "break")
        self.assertEqual(app.renderer.cut_ranges, [])
        self.assertEqual(len(app.renderer.data_processor.df), 1)
        self.assertEqual(app.undo_labels, ["刪除句"])
        self.assertTrue(app.refreshed_panel)
        self.assertTrue(app.refreshed_preview)

    def test_cut_sentence_marks_range_and_deletes_row(self):
        app = EditingHarness()

        result = app.cut_selected_dialogue_range()

        self.assertEqual(result, "break")
        self.assertEqual(app.renderer.cut_ranges, [(0.0, 1.0)])
        self.assertEqual(len(app.renderer.data_processor.df), 1)
        self.assertEqual(app.undo_labels, ["剪去片段"])
        self.assertTrue(app.logs)


class RendererTests(unittest.TestCase):
    def test_cut_ranges_are_normalized(self):
        renderer = VideoRenderer()

        renderer.set_cut_ranges([(2.0, 3.0), (1.0, 2.02), (4.0, 4.01)])

        self.assertEqual(renderer.cut_ranges, [(1.0, 3.0)])
        self.assertTrue(renderer._frame_in_cut_ranges(31, 30))
        self.assertFalse(renderer._frame_in_cut_ranges(91, 30))


if __name__ == "__main__":
    unittest.main()
