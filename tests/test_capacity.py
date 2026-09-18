import unittest

from services.capacity import (
    compute_quantity_allocation,
    compute_width_capacity,
    has_required_attribute_values,
    maximum_lanes,
    prorate_quantity,
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

    def test_variant_matches_all_required_values(self):
        self.assertTrue(
            has_required_attribute_values(
                product_value_ids=[10, 20, 30, 40],
                required_value_ids=[10, 20, 30],
            )
        )

    def test_variant_does_not_match_when_one_value_differs(self):
        self.assertFalse(
            has_required_attribute_values(
                product_value_ids=[10, 20, 99],
                required_value_ids=[10, 20, 30],
            )
        )

    def test_empty_filter_is_not_considered_compatible(self):
        self.assertFalse(
            has_required_attribute_values(
                product_value_ids=[10, 20, 30],
                required_value_ids=[],
            )
        )

    def test_consumption_is_prorated_by_roll_quantity(self):
        quantities = prorate_quantity(100, [100, 25, 25])

        self.assertAlmostEqual(quantities[0], 66.6666666667)
        self.assertAlmostEqual(quantities[1], 16.6666666667)
        self.assertAlmostEqual(quantities[2], 16.6666666666)
        self.assertAlmostEqual(sum(quantities), 100)

    def test_proration_without_weights_allocates_nothing(self):
        self.assertEqual(prorate_quantity(25, [0, 0]), [0.0, 0.0])

if __name__ == "__main__":
    unittest.main()
