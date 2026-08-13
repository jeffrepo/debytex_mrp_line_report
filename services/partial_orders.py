"""Pure helpers for totals across partial manufacturing orders."""


def _non_negative(value):
    try:
        return max(float(value or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def summarize_partial_orders(
    *, initial_demand=0, planned_quantities=(), produced_quantities=()
):
    planned_total = sum(_non_negative(value) for value in planned_quantities)
    requested = _non_negative(initial_demand) or planned_total
    produced = sum(_non_negative(value) for value in produced_quantities)
    return {
        "rolls_requested": requested,
        "current_roll": produced,
        "rolls_missing": max(requested - produced, 0.0),
    }
