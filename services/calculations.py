"""Pure production calculations shared by the Odoo model and unit tests."""

from __future__ import annotations

import math
from datetime import datetime, timedelta


def _non_negative(value):
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def format_remaining_time(hours):
    """Match the Spanish duration presentation used by the HTML prototype."""
    hours = _non_negative(hours)
    if hours <= 0:
        return "0 minutos"

    total_minutes = round(hours * 60)
    days, remaining = divmod(total_minutes, 24 * 60)
    whole_hours, minutes = divmod(remaining, 60)
    parts = []

    if days:
        parts.append(f"{days} día{'s' if days != 1 else ''}")
    if whole_hours:
        parts.append(
            f"{whole_hours} hora{'s' if whole_hours != 1 else ''}"
        )
    if minutes or not parts:
        parts.append(f"{minutes} minuto{'s' if minutes != 1 else ''}")
    return ", ".join(parts)


def compute_production(
    *,
    rolls_requested=0,
    current_roll=0,
    rolls_per_axis=0,
    roll_length=0,
    winder_speed=0,
    belt_speed=0,
    manual_minutes=0,
    time_mode="manual",
    cutoff_datetime=None,
):
    """Apply the production rules from the approved standalone HTML.

    Rolls mounted on the same axis are produced simultaneously. Therefore,
    the remaining time is calculated from pending axes, always rounding the
    number of axes upwards.
    """
    requested = _non_negative(rolls_requested)
    in_progress = _non_negative(current_roll)
    per_axis = _non_negative(rolls_per_axis)
    length = _non_negative(roll_length)
    winder = _non_negative(winder_speed)
    belt = _non_negative(belt_speed)
    manual = _non_negative(manual_minutes)

    missing = max(0.0, requested - in_progress)
    pending_axes = math.ceil(missing / per_axis) if per_axis > 0 else 0

    minutes_per_axis = 0.0
    if time_mode == "manual" and manual > 0:
        minutes_per_axis = manual
    elif winder > 0 and length > 0:
        minutes_per_axis = length / winder

    remaining_hours = (pending_axes * minutes_per_axis) / 60.0
    k_constant = (winder / belt) if belt > 0 else 0.0

    estimated_finish = None
    if cutoff_datetime and remaining_hours > 0:
        if not isinstance(cutoff_datetime, datetime):
            raise TypeError("cutoff_datetime must be a datetime instance")
        estimated_finish = cutoff_datetime + timedelta(hours=remaining_hours)

    return {
        "rolls_missing": missing,
        "pending_axes": pending_axes,
        "minutes_per_axis": minutes_per_axis,
        "remaining_hours": remaining_hours,
        "remaining_time_text": format_remaining_time(remaining_hours),
        "estimated_finish": estimated_finish,
        "k_constant": k_constant,
    }
