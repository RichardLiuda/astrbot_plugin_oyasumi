from __future__ import annotations


def format_duration_human(duration_minutes: int | None) -> str:
    if duration_minutes is None:
        return "-"
    if duration_minutes < 0:
        return "0分钟"

    hours, minutes = divmod(duration_minutes, 60)
    if hours == 0:
        return f"{minutes}分钟"
    return f"{hours}小时{minutes}分钟"
