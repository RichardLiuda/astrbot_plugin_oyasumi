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

    async def build_group_overview(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        include_auto_fill = self.settings.include_auto_fill_in_stats
        summary = await self.build_summary(
            user_id=None,
            start_date=start_date,
            end_date=end_date,
        )
        active_user_count = await self.repository.query_active_user_count(
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        daily_rows = await self.repository.query_daily_group_metrics(
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        sleep_heatmap = await self.repository.query_hourly_distribution(
            event="sleep",
            user_id=None,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        wake_heatmap = await self.repository.query_hourly_distribution(
            event="wake",
            user_id=None,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        daily_series = _fill_daily_series(
            start_date=start_date,
            end_date=end_date,
            rows=daily_rows,
        )
        auto_fill_session_count = sum(
            1 for row in summary.records if int(row.get("is_auto_filled") or 0) == 1
        )
        auto_fill_ratio = (
            round(auto_fill_session_count / summary.total_sessions, 4)
            if summary.total_sessions
            else 0.0
        )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "kpis": {
                "active_user_count": active_user_count,
                "total_sessions": summary.total_sessions,
                "total_sleep_minutes": summary.total_sleep_minutes,
                "avg_sleep_minutes": summary.avg_sleep_minutes,
                "open_session_count": summary.open_session_count,
                "orphan_morning_count": summary.orphan_morning_count,
                "auto_fill_ratio": auto_fill_ratio,
                "auto_fill_session_count": auto_fill_session_count,
            },
            "daily_series": daily_series,
            "sleep_heatmap": sleep_heatmap,
            "wake_heatmap": wake_heatmap,
        }

    async def build_leaderboard(
        self,
        *,
        start_date: str,
        end_date: str,
        limit: int = 10,
        metric: str = "activity",
    ) -> dict[str, Any]:
        selected_metric = (metric or "activity").strip().lower()
        if selected_metric != "activity":
            raise ValueError(
                "unsupported metric, currently only 'activity' is supported"
            )
        items = await self.repository.query_leaderboard_activity(
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=self.settings.include_auto_fill_in_stats,
            limit=limit,
        )
        return {
            "metric": selected_metric,
            "limit": max(1, min(limit, 100)),
            "items": items,
        }

    async def build_user_insight(
        self,
        *,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        data = await self.repository.query_user_overview(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=self.settings.include_auto_fill_in_stats,
        )
        records = data.get("records") or []
        total_sleep_minutes = sum(
            int(row.get("duration_minutes") or 0) for row in records
        )
        total_sessions = len(records)
        avg_sleep_minutes = (
            int(total_sleep_minutes / total_sessions) if total_sessions else 0
        )
        late_sleep_count = sum(
            1
            for row in records
            if _is_late_sleep_time(str(row.get("sleep_time") or ""))
        )
        late_sleep_rate = (
            round(late_sleep_count / total_sessions, 4) if total_sessions else 0.0
        )
        daily_series = _fill_daily_series(
            start_date=start_date,
            end_date=end_date,
            rows=data.get("daily_series") or [],
        )
        sleep_hourly = _aggregate_hourly(data.get("sleep_heatmap") or [])
        wake_hourly = _aggregate_hourly(data.get("wake_heatmap") or [])
        return {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date,
            "kpis": {
                "total_sessions": total_sessions,
                "total_sleep_minutes": total_sleep_minutes,
                "avg_sleep_minutes": avg_sleep_minutes,
                "open_session_count": int(data.get("open_session_count") or 0),
                "orphan_morning_count": int(data.get("orphan_morning_count") or 0),
                "late_sleep_count": late_sleep_count,
                "late_sleep_rate": late_sleep_rate,
            },
            "daily_series": daily_series,
            "sleep_hourly": sleep_hourly,
            "wake_hourly": wake_hourly,
            "recent_sessions": records[:100],
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


def _fill_daily_series(
    *,
    start_date: str,
    end_date: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {
        str(row.get("stat_date")): row for row in rows if row.get("stat_date")
    }
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    output: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        key = cursor.strftime("%Y-%m-%d")
        row = index.get(key, {})
        output.append(
            {
                "stat_date": key,
                "total_minutes": int(row.get("total_minutes") or 0),
                "session_count": int(row.get("session_count") or 0),
                "active_user_count": int(row.get("active_user_count") or 0),
            }
        )
        cursor += timedelta(days=1)
    return output


def _aggregate_hourly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = dict.fromkeys(range(24), 0)
    for row in rows:
        hour = int(row.get("hour") or 0) % 24
        buckets[hour] += int(row.get("count") or 0)
    return [{"hour": hour, "count": buckets[hour]} for hour in range(24)]


def _is_late_sleep_time(sleep_time_text: str) -> bool:
    if len(sleep_time_text) < 13:
        return False
    hour_text = sleep_time_text[11:13]
    try:
        hour = int(hour_text)
    except ValueError:
        return False
    return hour >= 23 or hour < 6


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
        try:
            end_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            start = end_obj - timedelta(days=6)
        except ValueError:
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
