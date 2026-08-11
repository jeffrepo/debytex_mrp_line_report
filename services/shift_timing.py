from datetime import datetime


def seconds_between(start_datetime, end_datetime):
    """Return a positive amount of seconds between two datetimes."""
    if not start_datetime or not end_datetime:
        return 0.0
    if not isinstance(start_datetime, datetime) or not isinstance(
        end_datetime, datetime
    ):
        return 0.0
    return max((end_datetime - start_datetime).total_seconds(), 0.0)


def effective_elapsed_seconds(
    accumulated_seconds,
    running_since,
    sampled_at,
    is_running,
):
    elapsed = max(float(accumulated_seconds or 0.0), 0.0)
    if is_running:
        elapsed += seconds_between(running_since, sampled_at)
    return elapsed


def format_duration(seconds):
    total_seconds = max(int(seconds or 0), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
