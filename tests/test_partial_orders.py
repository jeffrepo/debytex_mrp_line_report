import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "services" / "partial_orders.py"
SPEC = importlib.util.spec_from_file_location("debytex_partial_orders", MODULE_PATH)
PARTIAL_ORDERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARTIAL_ORDERS)


class TestPartialOrderTotals(unittest.TestCase):
    def test_uses_initial_demand_and_accumulated_production(self):
        result = PARTIAL_ORDERS.summarize_partial_orders(
            initial_demand=60,
            planned_quantities=[24, 36],
            produced_quantities=[24, 8],
        )
        self.assertEqual(result["rolls_requested"], 60)
        self.assertEqual(result["current_roll"], 32)
        self.assertEqual(result["rolls_missing"], 28)

    def test_falls_back_to_sum_of_planned_partial_orders(self):
        result = PARTIAL_ORDERS.summarize_partial_orders(
            initial_demand=0,
            planned_quantities=[24, 36],
            produced_quantities=[24, 8],
        )
        self.assertEqual(result["rolls_requested"], 60)

    def test_completed_chain_never_has_negative_missing_rolls(self):
        result = PARTIAL_ORDERS.summarize_partial_orders(
            initial_demand=10,
            planned_quantities=[10],
            produced_quantities=[12],
        )
        self.assertEqual(result["rolls_missing"], 0)
