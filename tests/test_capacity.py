import unittest

from services.capacity import (
    compute_quantity_allocation,
    compute_width_capacity,
    maximum_lanes,
)


class TestWidthCapacity(unittest.TestCase):
    def test_mixed_products_fit_with_ten_centimeters_free(self):
        values = compute_width_capacity(
            useful_width_cm=320,
            allocations=(
                {"width_cm": 160, "lanes": 1},
                {"width_cm": 90, "lanes": 1},
                {"width_cm": 60, "lanes": 1},
            ),
        )

        self.assertEqual(values["occupied_width_cm"], 310)
        self.assertEqual(values["free_width_cm"], 10)
        self.assertFalse(values["over_capacity"])
        self.assertAlmostEqual(values["utilization_percentage"], 96.875)

    def test_over_capacity_is_visible_without_negative_free_width(self):
        values = compute_width_capacity(
            useful_width_cm=240,
            allocations=({"width_cm": 130, "lanes": 2},),
        )

        self.assertEqual(values["occupied_width_cm"], 260)
        self.assertEqual(values["free_width_cm"], 0)
        self.assertEqual(values["excess_width_cm"], 20)
        self.assertTrue(values["over_capacity"])

    def test_maximum_lanes_uses_full_product_width(self):
        self.assertEqual(
            maximum_lanes(useful_width_cm=320, product_width_cm=90), 3
        )
        self.assertEqual(
            maximum_lanes(useful_width_cm=320, product_width_cm=0), 0
        )

    def test_invalid_values_are_safe(self):
        values = compute_width_capacity(
            useful_width_cm="invalid",
            allocations=({"width_cm": -20, "lanes": -1},),
        )

        self.assertEqual(values["occupied_width_cm"], 0)
        self.assertEqual(values["utilization_percentage"], 0)

    def test_explicit_processing_quantity_creates_a_remainder(self):
        values = compute_quantity_allocation(
            available_quantity=100,
            quantity_to_process=25,
        )

        self.assertEqual(values["quantity_to_process"], 25)
        self.assertEqual(values["remaining_quantity"], 75)
        self.assertEqual(values["allocation_percentage"], 25)
        self.assertTrue(values["is_partial"])
        self.assertFalse(values["overallocated"])

    def test_percentage_is_kept_as_a_legacy_fallback(self):
        values = compute_quantity_allocation(
            available_quantity=80,
            allocation_percentage=25,
        )

        self.assertEqual(values["quantity_to_process"], 20)
        self.assertEqual(values["remaining_quantity"], 60)

    def test_quantity_allocation_reports_excess(self):
        values = compute_quantity_allocation(
            available_quantity=10,
            quantity_to_process=11,
        )

        self.assertTrue(values["overallocated"])
        self.assertEqual(values["remaining_quantity"], 0)


if __name__ == "__main__":
    unittest.main()
