import unittest

from services.dashboard import merge_capacity_orders


class TestCapacityDashboard(unittest.TestCase):
    def test_active_capacity_orders_are_first_and_not_duplicated(self):
        dashboard = {
            10: {
                "id": 10,
                "workcenter_name": "Línea A",
                "ordenes": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
            }
        }
        capacity = {
            10: {
                "id": 10,
                "workcenter_name": "Línea A",
                "ordenes": [{"id": 5}, {"id": 2}],
            }
        }

        result = merge_capacity_orders(dashboard, capacity)

        self.assertEqual(
            [order["id"] for order in result[10]["ordenes"]],
            [5, 2, 1, 3, 4],
        )
        self.assertEqual(
            [order["id"] for order in dashboard[10]["ordenes"]],
            [1, 2, 3, 4],
        )

    def test_capacity_order_can_create_a_missing_workcenter_group(self):
        capacity = {
            20: {
                "id": 20,
                "workcenter_name": "Línea B",
                "ordenes": [{"id": 8}],
            }
        }

        result = merge_capacity_orders({}, capacity)

        self.assertEqual(result[20]["workcenter_name"], "Línea B")
        self.assertEqual(result[20]["ordenes"], [{"id": 8}])


if __name__ == "__main__":
    unittest.main()
