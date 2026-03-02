from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .config import PluginSettings
from .repository import OyasumiRepository


@dataclass
class StatsSummary:
    user_id: str | None
    start_date: str
    end_date: str
    total_sessions: int
    total_sleep_minutes: int
    avg_sleep_minutes: int
    earliest_sleep_time: str | None
    latest_sleep_time: str | None
    earliest_wake_time: str | None
    latest_wake_time: str | None
    open_session_count: int
    orphan_morning_count: int
    records: list[dict[str, Any]]

    def to_text(self, *, include_records_limit: int = 8) -> str:
        user_label = self.user_id or "全部用户"
        lines = [
            f"统计对象：{user_label}",
            f"统计区间：{self.start_date} ~ {self.end_date}",
            f"闭合会话数：{self.total_sessions}",
            f"总睡眠时长：{self.total_sleep_minutes} 分钟",
            f"平均睡眠时长：{self.avg_sleep_minutes} 分钟",
            f"最早入睡：{self.earliest_sleep_time or '-'}",
            f"最晚入睡：{self.latest_sleep_time or '-'}",
            f"最早醒来：{self.earliest_wake_time or '-'}",
            f"最晚醒来：{self.latest_wake_time or '-'}",
            f"当前进行中会话：{self.open_session_count}",
            f"孤立早安事件：{self.orphan_morning_count}",
        ]
        if not self.records:
            lines.append("区间内暂无闭合会话记录。")
            return "\n".join(lines)

        lines.append("最近会话：")
        for row in self.records[:include_records_limit]:
            lines.append(
                f"- #{row['id']} | 日期:{row['stat_date']} | 入睡:{row['sleep_time']} | "
                f"醒来:{row['wake_time']} | 时长:{row['duration_minutes']}分钟"
            )
        return "\n".join(lines)


class StatsService:
    def __init__(self, repository: OyasumiRepository, settings: PluginSettings):
        self.repository = repository
        self.settings = settings

    async def build_summary(
        self,
        *,
        user_id: str | None,
        start_date: str,
        end_date: str,
    ) -> StatsSummary:
        records = await self.repository.query_closed_sessions_for_stats(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=self.settings.include_auto_fill_in_stats,
        )
        open_count = await self.repository.get_open_session_count(user_id=user_id)
        orphan_count = await self.repository.count_orphan_morning_events(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
        )

        total_sleep_minutes = sum(
            int(row.get("duration_minutes") or 0) for row in records
        )
        total_sessions = len(records)
        avg_sleep_minutes = (
            int(total_sleep_minutes / total_sessions) if total_sessions else 0
        )

        earliest_sleep_time = _pick_time(records, "sleep_time", min)
        latest_sleep_time = _pick_time(records, "sleep_time", max)
        earliest_wake_time = _pick_time(records, "wake_time", min)
        latest_wake_time = _pick_time(records, "wake_time", max)

        return StatsSummary(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            total_sessions=total_sessions,
            total_sleep_minutes=total_sleep_minutes,
            avg_sleep_minutes=avg_sleep_minutes,
            earliest_sleep_time=earliest_sleep_time,
            latest_sleep_time=latest_sleep_time,
            earliest_wake_time=earliest_wake_time,
            latest_wake_time=latest_wake_time,
            open_session_count=open_count,
            orphan_morning_count=orphan_count,
            records=records,
        )

    async def build_dashboard(
        self,
        *,
        user_id: str,
        recent_days: int = 7,
    ) -> dict[str, Any]:
        today = date.today()
        start_date_obj = today - timedelta(days=max(1, recent_days) - 1)
        start_date = start_date_obj.strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        daily = await self.repository.query_daily_sleep_minutes(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=self.settings.include_auto_fill_in_stats,
        )
        open_count = await self.repository.get_open_session_count(user_id=user_id)

        total_minutes = sum(int(row.get("total_minutes") or 0) for row in daily)
        total_sessions = sum(int(row.get("session_count") or 0) for row in daily)
        avg_minutes = int(total_minutes / total_sessions) if total_sessions else 0
        return {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date,
            "open_session_count": open_count,
            "total_sleep_minutes": total_minutes,
            "avg_sleep_minutes": avg_minutes,
            "daily": daily,
        }


def _pick_time(
    records: list[dict[str, Any]],
    key: str,
    picker,
) -> str | None:
    values = [str(row[key]) for row in records if row.get(key)]
    if not values:
        return None
    return picker(values)


def resolve_date_range(start_date: str = "", end_date: str = "") -> tuple[str, str]:
    today = date.today()
    if not start_date and not end_date:
        start = today - timedelta(days=6)
        end = today
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if start_date and not end_date:
        end = today
        return (start_date, end.strftime("%Y-%m-%d"))
    if end_date and not start_date:
        start = today - timedelta(days=6)
        return (start.strftime("%Y-%m-%d"), end_date)
    return (start_date, end_date)


def validate_date_text(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False
