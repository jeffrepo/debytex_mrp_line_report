def merge_capacity_orders(dashboard_data, capacity_groups):
    """Place active capacity orders first without duplicating base cards."""
    capacity_order_ids = {
        order.get("id")
        for group in capacity_groups.values()
        for order in group.get("ordenes", [])
        if order.get("id")
    }
    result = {
        workcenter_id: {
            **group,
            "ordenes": [
                order
                for order in group.get("ordenes", [])
                if order.get("id") not in capacity_order_ids
            ],
        }
        for workcenter_id, group in dashboard_data.items()
    }
    for workcenter_id, capacity_group in capacity_groups.items():
        group = result.setdefault(
            workcenter_id,
            {
                "id": capacity_group.get("id", workcenter_id),
                "workcenter_name": capacity_group.get(
                    "workcenter_name", "Sin línea asignada"
                ),
                "ordenes": [],
            },
        )
        group["ordenes"] = (
            list(capacity_group.get("ordenes", [])) + group["ordenes"]
        )
    return result
