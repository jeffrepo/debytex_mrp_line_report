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


def move_dashboard_order(ordered_ids, production_id, position):
    """Move one production to a one-based position and keep unique IDs."""
    unique_ids = []
    for record_id in ordered_ids:
        if record_id not in unique_ids:
            unique_ids.append(record_id)
    if production_id not in unique_ids:
        return unique_ids
    unique_ids.remove(production_id)
    target_index = max(0, min(int(position or 1) - 1, len(unique_ids)))
    unique_ids.insert(target_index, production_id)
    return unique_ids
