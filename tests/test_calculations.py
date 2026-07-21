import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "services" / "calculations.py"
SPEC = importlib.util.spec_from_file_location("debytex_calculations", MODULE_PATH)
CALCULATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALCULATIONS)


class TestProductionCalculations(unittest.TestCase):
    def test_automatic_time_and_k_match_prototype(self):
        cutoff = datetime(2026, 7, 21, 8, 0)
        result = CALCULATIONS.compute_production(
            rolls_requested=100,
            current_roll=20,
            rolls_per_axis=4,
            roll_length=2000,
            winder_speed=100,
            belt_speed=80,
            time_mode="auto",
            cutoff_datetime=cutoff,
        )

        self.assertEqual(result["rolls_missing"], 80)
        self.assertEqual(result["pending_axes"], 20)
        self.assertEqual(result["minutes_per_axis"], 20)
        self.assertAlmostEqual(result["remaining_hours"], 20 / 3)
        self.assertEqual(result["remaining_time_text"], "6 horas, 40 minutos")
        self.assertEqual(result["estimated_finish"], datetime(2026, 7, 21, 14, 40))
        self.assertEqual(result["k_constant"], 1.25)

    def test_manual_time_is_applied_per_pending_axis(self):
        result = CALCULATIONS.compute_production(
            rolls_requested=10,
            current_roll=1,
            rolls_per_axis=3,
            manual_minutes=12,
            time_mode="manual",
        )

        self.assertEqual(result["rolls_missing"], 9)
        self.assertEqual(result["pending_axes"], 3)
        self.assertEqual(result["minutes_per_axis"], 12)
        self.assertEqual(result["remaining_time_text"], "36 minutos")

    def test_axes_are_always_rounded_up(self):
        result = CALCULATIONS.compute_production(
            rolls_requested=11,
            current_roll=2,
            rolls_per_axis=4,
            manual_minutes=10,
        )
        self.assertEqual(result["pending_axes"], 3)

    def test_manual_mode_falls_back_to_winder_when_manual_value_is_empty(self):
        result = CALCULATIONS.compute_production(
            rolls_requested=8,
            current_roll=0,
            rolls_per_axis=2,
            roll_length=600,
            winder_speed=60,
            manual_minutes=0,
            time_mode="manual",
        )
        self.assertEqual(result["minutes_per_axis"], 10)
        self.assertEqual(result["remaining_time_text"], "40 minutos")

    def test_negative_values_are_clamped_and_completed_order_has_no_finish(self):
        result = CALCULATIONS.compute_production(
            rolls_requested=-10,
            current_roll=5,
            rolls_per_axis=-2,
            cutoff_datetime=datetime(2026, 7, 21, 8, 0),
        )
        self.assertEqual(result["rolls_missing"], 0)
        self.assertEqual(result["pending_axes"], 0)
        self.assertEqual(result["remaining_time_text"], "0 minutos")
        self.assertIsNone(result["estimated_finish"])

    def test_duration_format_includes_days(self):
        self.assertEqual(
            CALCULATIONS.format_remaining_time(26.5),
            "1 día, 2 horas, 30 minutos",
        )


if __name__ == "__main__":
    unittest.main()
