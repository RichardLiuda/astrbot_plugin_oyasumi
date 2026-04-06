from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .config import PluginSettings
from .repository import DATETIME_FMT, OyasumiRepository, format_dt
from .trigger_matcher import EVENT_GOOD_MORNING, EVENT_GOOD_NIGHT


@dataclass
class EventProcessResult:
    event_id: int
    event_type: str
    action: str
    session_id: int | None
    sleep_time: str | None
    wake_time: str | None
    duration_minutes: int | None
    internal_note: str
    orphaned: bool = False
    auto_filled: bool = False
    open_session_count: int = 0
    abandoned_count: int = 0


class SessionService:
    def __init__(self, repository: OyasumiRepository, settings: PluginSettings):
        self.repository = repository
        self.settings = settings

    async def process_event(
        self,
        *,
        user_id: str,
        event_type: str,
        event_time: datetime,
        raw_message: str,
        matched_pattern: str,
    ) -> EventProcessResult:
        if event_type == EVENT_GOOD_NIGHT:
            return await self._process_good_night(
                user_id=user_id,
                event_time=event_time,
                raw_message=raw_message,
                matched_pattern=matched_pattern,
            )
        return await self._process_good_morning(
            user_id=user_id,
            event_time=event_time,
            raw_message=raw_message,
            matched_pattern=matched_pattern,
        )

    async def _process_good_night(
        self,
        *,
        user_id: str,
        event_time: datetime,
        raw_message: str,
        matched_pattern: str,
    ) -> EventProcessResult:
        async with self.repository.transaction() as conn:
            abandoned_count = await self.repository.abandon_timeout_open_sessions(
                user_id,
                event_time - timedelta(hours=self.settings.max_open_session_hours),
                conn=conn,
            )
            open_session = await self.repository.get_latest_open_session(
                user_id, conn=conn
            )
            action = "night_open_created"
            event_status = "processed"
            internal_note = "晚安事件已记录。"
            session_id: int | None = None

            if open_session is None:
                session_id = await self.repository.create_open_session(
                    user_id=user_id,
                    sleep_time=event_time,
                    source="regex",
                    conn=conn,
                )
                sleep_time = format_dt(event_time)
            else:
                session_id = int(open_session["id"])
                policy = self.settings.duplicate_night_policy
                if policy == "ignore":
                    action = "night_duplicate_ignored"
                    event_status = "ignored"
                    internal_note = "检测到重复晚安，本次未创建新会话。"
                    sleep_time = str(open_session.get("sleep_time") or "")
                elif policy == "update_open":
                    await self.repository.update_open_session_sleep_time(
                        session_id,
                        event_time,
                        conn=conn,
                    )
                    action = "night_duplicate_updated_open"
                    internal_note = "检测到重复晚安，已更新进行中会话的入睡时间。"
                    sleep_time = format_dt(event_time)
                else:
                    session_id = await self.repository.create_open_session(
                        user_id=user_id,
                        sleep_time=event_time,
                        source="regex",
                        conn=conn,
                    )
                    action = "night_duplicate_created_new"
                    internal_note = "检测到重复晚安，已按策略新建进行中会话。"
                    sleep_time = format_dt(event_time)

            event_id = await self.repository.insert_event(
                user_id=user_id,
                event_type=EVENT_GOOD_NIGHT,
                event_time=event_time,
                matched_pattern=matched_pattern,
                raw_message=raw_message,
                session_id=session_id,
                event_status=event_status,
                metadata={"action": action},
                conn=conn,
            )
            open_session_count = await self.repository.get_open_session_count(
                user_id=user_id,
                conn=conn,
            )
        return EventProcessResult(
            event_id=event_id,
            event_type=EVENT_GOOD_NIGHT,
            action=action,
            session_id=session_id,
            sleep_time=sleep_time,
            wake_time=None,
            duration_minutes=None,
            internal_note=internal_note,
            orphaned=False,
            auto_filled=False,
            open_session_count=open_session_count,
            abandoned_count=abandoned_count,
        )

    async def _process_good_morning(
        self,
        *,
        user_id: str,
        event_time: datetime,
        raw_message: str,
        matched_pattern: str,
    ) -> EventProcessResult:
        async with self.repository.transaction() as conn:
            abandoned_count = await self.repository.abandon_timeout_open_sessions(
                user_id,
                event_time - timedelta(hours=self.settings.max_open_session_hours),
                conn=conn,
            )
            open_session = await self.repository.get_latest_open_session(
                user_id=user_id,
                conn=conn,
            )

            session_id: int | None = None
            action = "morning_orphan_warning"
            event_status = "orphan"
            internal_note = "已记录早安事件，但没有可闭合的晚安会话。"
            sleep_time: str | None = None
            wake_time: str | None = None
            duration_minutes: int | None = None
            orphaned = False
            auto_filled = False

            if open_session is not None:
                session_id = int(open_session["id"])
                raw_sleep_time = str(open_session.get("sleep_time") or "")
                sleep_dt = datetime.strptime(raw_sleep_time, DATETIME_FMT)
                safe_wake_dt = event_time if event_time >= sleep_dt else sleep_dt
                await self.repository.close_session(
                    session_id=session_id,
                    wake_time=safe_wake_dt,
                    conn=conn,
                )
                action = "morning_closed_session"
                event_status = "processed"
                internal_note = "早安事件已记录，已闭合最近进行中会话。"
                sleep_time = format_dt(sleep_dt)
                wake_time = format_dt(safe_wake_dt)
                duration_minutes = max(
                    int((safe_wake_dt - sleep_dt).total_seconds() // 60),
                    0,
                )
            else:
                orphan_policy = self.settings.orphan_morning_policy
                orphaned = True
                if orphan_policy == "create_closed_session":
                    sleep_dt = event_time - timedelta(
                        hours=self.settings.auto_fill_default_hours
                    )
                    session_id = await self.repository.create_closed_session(
                        user_id=user_id,
                        sleep_time=sleep_dt,
                        wake_time=event_time,
                        source="auto_fill",
                        is_auto_filled=True,
                        auto_fill_reason="orphan_morning",
                        conn=conn,
                    )
                    action = "morning_auto_filled_session"
                    event_status = "auto_filled"
                    internal_note = "未找到进行中会话，已按策略自动补全一条睡眠会话。"
                    sleep_time = format_dt(sleep_dt)
                    wake_time = format_dt(event_time)
                    duration_minutes = int(
                        (event_time - sleep_dt).total_seconds() // 60
                    )
                    auto_filled = True

            event_id = await self.repository.insert_event(
                user_id=user_id,
                event_type=EVENT_GOOD_MORNING,
                event_time=event_time,
                matched_pattern=matched_pattern,
                raw_message=raw_message,
                session_id=session_id,
                event_status=event_status,
                metadata={"action": action},
                conn=conn,
            )
            open_session_count = await self.repository.get_open_session_count(
                user_id=user_id,
                conn=conn,
            )

        return EventProcessResult(
            event_id=event_id,
            event_type=EVENT_GOOD_MORNING,
            action=action,
            session_id=session_id,
            sleep_time=sleep_time,
            wake_time=wake_time,
            duration_minutes=duration_minutes,
            internal_note=internal_note,
            orphaned=orphaned,
            auto_filled=auto_filled,
            open_session_count=open_session_count,
            abandoned_count=abandoned_count,
        )

    async def update_session_by_command(
        self,
        *,
        actor_user_id: str,
        is_admin: bool,
        session_id: int,
        sleep_time_str: str | None,
        wake_time_str: str | None,
    ) -> str:
        session = await self.repository.get_session_by_id(session_id)
        if session is None:
            return f"未找到会话：{session_id}"

        target_user_id = str(session["user_id"])
        if not is_admin and (not self.settings.allow_user_edit_self):
            return "当前配置不允许普通用户修正会话。"
        if not is_admin and actor_user_id != target_user_id:
            return "你只能修改自己的会话记录。"

        try:
            sleep_dt = _parse_datetime_like(sleep_time_str) if sleep_time_str else None
            wake_dt = _parse_datetime_like(wake_time_str) if wake_time_str else None
        except ValueError as exc:
            return f"时间格式错误：{exc}"

        old_sleep = _parse_datetime_like(session.get("sleep_time"))
        old_wake = _parse_datetime_like(session.get("wake_time"))

        new_sleep = sleep_dt if sleep_dt is not None else old_sleep
        new_wake = wake_dt if wake_dt is not None else old_wake

        if new_sleep is None and new_wake is not None:
            return "存在醒来时间但没有入睡时间，请同时提供入睡时间。"
        if new_sleep and new_wake and new_wake < new_sleep:
            return "醒来时间不能早于入睡时间。"
        if new_sleep is None and new_wake is None:
            return "没有可更新的时间字段。"

        if new_sleep and new_wake:
            new_status = "closed"
        elif new_sleep and not new_wake:
            new_status = "open"
        else:
            new_status = "abandoned"

        async with self.repository.transaction() as conn:
            await self.repository.update_session(
                session_id=session_id,
                sleep_time=new_sleep,
                wake_time=new_wake,
                status=new_status,
                source="manual_edit",
                conn=conn,
            )
            await self.repository.insert_event(
                user_id=target_user_id,
                event_type="manual_edit",
                event_time=datetime.now(),
                matched_pattern="",
                raw_message="manual_update",
                session_id=session_id,
                event_status="manual",
                metadata={
                    "actor_user_id": actor_user_id,
                    "is_admin": is_admin,
                    "new_status": new_status,
                },
                conn=conn,
            )

        return (
            f"会话 {session_id} 已更新。\n"
            f"入睡：{format_dt(new_sleep) if new_sleep else '-'}\n"
            f"醒来：{format_dt(new_wake) if new_wake else '-'}\n"
            f"状态：{new_status}"
        )


def _parse_datetime_like(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError("请使用 YYYY-MM-DD HH:MM[:SS] 或 YYYY-MM-DDTHH:MM[:SS]")
