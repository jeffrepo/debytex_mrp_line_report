import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "services" / "shift_timing.py"
SPEC = importlib.util.spec_from_file_location("debytex_shift_timing", MODULE_PATH)
SHIFT_TIMING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHIFT_TIMING)


class TestShiftTiming(unittest.TestCase):
    def test_running_timer_adds_current_segment(self):
        result = SHIFT_TIMING.effective_elapsed_seconds(
            accumulated_seconds=120,
            running_since=datetime(2026, 8, 11, 8, 0, 0),
            sampled_at=datetime(2026, 8, 11, 8, 5, 30),
            is_running=True,
        )
        self.assertEqual(result, 450)

    def test_paused_timer_keeps_accumulated_value(self):
        result = SHIFT_TIMING.effective_elapsed_seconds(
            accumulated_seconds=450,
            running_since=None,
            sampled_at=datetime(2026, 8, 11, 8, 10, 0),
            is_running=False,
        )
        self.assertEqual(result, 450)

    def test_negative_intervals_are_ignored(self):
        result = SHIFT_TIMING.seconds_between(
            datetime(2026, 8, 11, 9, 0, 0),
            datetime(2026, 8, 11, 8, 0, 0),
        )
        self.assertEqual(result, 0)

    def test_duration_uses_unbounded_hours(self):
        self.assertEqual(SHIFT_TIMING.format_duration(93784), "26:03:04")


if __name__ == "__main__":
    unittest.main()
