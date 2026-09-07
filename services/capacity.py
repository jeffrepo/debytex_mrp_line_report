"""Pure helpers for previewing work-center width allocation."""

import math


def _non_negative(value):
    try:
        return max(float(value or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def compute_width_capacity(*, useful_width_cm, allocations=()):
    """Return occupied, available and utilization values for a width layout.

    Each allocation is a mapping containing ``width_cm`` and ``lanes``. This
    intentionally models only physical width; production compatibility and
    shift duration belong to later planning phases.
    """
    useful_width = _non_negative(useful_width_cm)
    occupied_width = sum(
        _non_negative(allocation.get("width_cm"))
        * max(int(_non_negative(allocation.get("lanes"))), 0)
        for allocation in allocations
    )
    free_width = max(useful_width - occupied_width, 0.0)
    excess_width = max(occupied_width - useful_width, 0.0)
    utilization = (
        occupied_width / useful_width * 100.0 if useful_width > 0 else 0.0
    )
    return {
        "useful_width_cm": useful_width,
        "occupied_width_cm": occupied_width,
        "free_width_cm": free_width,
        "excess_width_cm": excess_width,
        "utilization_percentage": utilization,
        "over_capacity": excess_width > 0,
    }


def maximum_lanes(*, useful_width_cm, product_width_cm):
    """Return how many equal-width product lanes fit in the useful width."""
    useful_width = _non_negative(useful_width_cm)
    product_width = _non_negative(product_width_cm)
    return int(math.floor(useful_width / product_width)) if product_width else 0
