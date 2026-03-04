from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from astrbot.api import logger

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def format_dt(dt: datetime) -> str:
    return dt.strftime(DATETIME_FMT)


class OyasumiRepository:
    def __init__(self, db_path: Path, init_sql_path: Path):
        self.db_path = Path(db_path)
        self.init_sql_path = Path(init_sql_path)
        self._conn: aiosqlite.Connection | None = None
        self._tx_lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        sql_script = self.init_sql_path.read_text(encoding="utf-8")
        await self._conn.executescript(sql_script)
        await self._conn.commit()
        logger.info("[oyasumi] repository initialized: %s", self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("repository not initialized")
        return self._conn

    @asynccontextmanager
    async def transaction(self):
        conn = await self._require_conn()
        async with self._tx_lock:
            await conn.execute("BEGIN")
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def _execute(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> aiosqlite.Cursor:
        active_conn = conn or await self._require_conn()
        cursor = await active_conn.execute(sql, params)
        if conn is None:
            await active_conn.commit()
        return cursor

    async def _fetch_one(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Any] | None:
        active_conn = conn or await self._require_conn()
        cursor = await active_conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def _fetch_all(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> list[dict[str, Any]]:
        active_conn = conn or await self._require_conn()
        cursor = await active_conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def abandon_timeout_open_sessions(
        self,
        user_id: str,
        threshold_dt: datetime,
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        cursor = await self._execute(
            """
            UPDATE sleep_session
            SET status='abandoned', updated_at=datetime('now', 'localtime')
            WHERE user_id = ?
              AND status = 'open'
              AND sleep_time IS NOT NULL
              AND sleep_time <= ?
            """,
            (user_id, format_dt(threshold_dt)),
            conn=conn,
        )
        return int(cursor.rowcount or 0)

    async def get_latest_open_session(
        self,
        user_id: str,
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Any] | None:
        return await self._fetch_one(
            """
            SELECT *
            FROM sleep_session
            WHERE user_id = ?
              AND status = 'open'
            ORDER BY datetime(sleep_time) DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
            conn=conn,
        )

    async def create_open_session(
        self,
        user_id: str,
        sleep_time: datetime,
        *,
        source: str = "regex",
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        cursor = await self._execute(
            """
            INSERT INTO sleep_session (
                user_id, sleep_time, wake_time, status, source,
                is_auto_filled, auto_fill_reason, created_at, updated_at
            )
            VALUES (?, ?, NULL, 'open', ?, 0, NULL, datetime('now', 'localtime'), datetime('now', 'localtime'))
            """,
            (user_id, format_dt(sleep_time), source),
            conn=conn,
        )
        return int(cursor.lastrowid)

    async def update_open_session_sleep_time(
        self,
        session_id: int,
        sleep_time: datetime,
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        cursor = await self._execute(
            """
            UPDATE sleep_session
            SET sleep_time = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
              AND status = 'open'
            """,
            (format_dt(sleep_time), session_id),
            conn=conn,
        )
        return int(cursor.rowcount or 0)

    async def close_session(
        self,
        session_id: int,
        wake_time: datetime,
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        cursor = await self._execute(
            """
            UPDATE sleep_session
            SET wake_time = ?, status = 'closed', updated_at = datetime('now', 'localtime')
            WHERE id = ?
              AND status = 'open'
            """,
            (format_dt(wake_time), session_id),
            conn=conn,
        )
        return int(cursor.rowcount or 0)

    async def create_closed_session(
        self,
        user_id: str,
        sleep_time: datetime,
        wake_time: datetime,
        *,
        source: str = "auto_fill",
        is_auto_filled: bool = True,
        auto_fill_reason: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        cursor = await self._execute(
            """
            INSERT INTO sleep_session (
                user_id, sleep_time, wake_time, status, source,
                is_auto_filled, auto_fill_reason, created_at, updated_at
            )
            VALUES (?, ?, ?, 'closed', ?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'))
            """,
            (
                user_id,
                format_dt(sleep_time),
                format_dt(wake_time),
                source,
                1 if is_auto_filled else 0,
                auto_fill_reason,
            ),
            conn=conn,
        )
        return int(cursor.lastrowid)

    async def insert_event(
        self,
        user_id: str,
        event_type: str,
        event_time: datetime,
        *,
        matched_pattern: str = "",
        raw_message: str = "",
        session_id: int | None = None,
        event_status: str = "processed",
        metadata: dict[str, Any] | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        cursor = await self._execute(
            """
            INSERT INTO sleep_event (
                user_id, event_type, event_time, matched_pattern, raw_message,
                session_id, event_status, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                user_id,
                event_type,
                format_dt(event_time),
                matched_pattern,
                raw_message,
                session_id,
                event_status,
                metadata_json,
            ),
            conn=conn,
        )
        return int(cursor.lastrowid)

    async def get_open_session_count(
        self,
        user_id: str | None = None,
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        if user_id:
            row = await self._fetch_one(
                "SELECT COUNT(1) AS cnt FROM sleep_session WHERE status='open' AND user_id = ?",
                (user_id,),
                conn=conn,
            )
        else:
            row = await self._fetch_one(
                "SELECT COUNT(1) AS cnt FROM sleep_session WHERE status='open'",
                (),
                conn=conn,
            )
        return int((row or {}).get("cnt", 0))

    async def get_session_by_id(self, session_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            "SELECT * FROM sleep_session WHERE id = ?",
            (session_id,),
        )

    async def update_session(
        self,
        session_id: int,
        sleep_time: datetime | None,
        wake_time: datetime | None,
        status: str,
        *,
        source: str = "manual_edit",
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        cursor = await self._execute(
            """
            UPDATE sleep_session
            SET sleep_time = ?,
                wake_time = ?,
                status = ?,
                source = ?,
                updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (
                format_dt(sleep_time) if sleep_time else None,
                format_dt(wake_time) if wake_time else None,
                status,
                source,
                session_id,
            ),
            conn=conn,
        )
        return int(cursor.rowcount or 0)

    async def list_sessions(
        self,
        *,
        user_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        if user_id:
            return await self._fetch_all(
                """
                SELECT
                    id, user_id, sleep_time, wake_time, status, source, is_auto_filled, auto_fill_reason,
                    CAST((JULIANDAY(wake_time) - JULIANDAY(sleep_time)) * 24 * 60 AS INTEGER) AS duration_minutes,
                    created_at, updated_at
                FROM sleep_session
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        return await self._fetch_all(
            """
            SELECT
                id, user_id, sleep_time, wake_time, status, source, is_auto_filled, auto_fill_reason,
                CAST((JULIANDAY(wake_time) - JULIANDAY(sleep_time)) * 24 * 60 AS INTEGER) AS duration_minutes,
                created_at, updated_at
            FROM sleep_session
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def list_user_ids(self, *, limit: int = 200) -> list[str]:
        limit = max(1, min(limit, 1000))
        rows = await self._fetch_all(
            """
            SELECT user_id, MAX(last_seen) AS latest_seen
            FROM (
                SELECT user_id, updated_at AS last_seen
                FROM sleep_session
                WHERE user_id IS NOT NULL AND user_id != ''
                UNION ALL
                SELECT user_id, event_time AS last_seen
                FROM sleep_event
                WHERE user_id IS NOT NULL AND user_id != ''
            ) t
            GROUP BY user_id
            ORDER BY datetime(latest_seen) DESC, user_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [str(row["user_id"]) for row in rows if row.get("user_id")]

    async def query_closed_sessions_for_stats(
        self,
        *,
        user_id: str | None,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
    ) -> list[dict[str, Any]]:
        user_filter_sql = ""
        auto_fill_filter_sql = ""
        params: list[Any] = [day_boundary_hour]
        if user_id:
            user_filter_sql = " AND user_id = ? "
            params.append(user_id)
        if not include_auto_fill:
            auto_fill_filter_sql = " AND is_auto_filled = 0 "
        params.extend([start_date, end_date])

        sql = f"""
            SELECT *
            FROM (
                SELECT
                    id,
                    user_id,
                    sleep_time,
                    wake_time,
                    status,
                    source,
                    is_auto_filled,
                    auto_fill_reason,
                    CASE
                        WHEN CAST(strftime('%H', sleep_time) AS INTEGER) < ?
                        THEN date(sleep_time, '-1 day')
                        ELSE date(sleep_time)
                    END AS stat_date,
                    CAST((JULIANDAY(wake_time) - JULIANDAY(sleep_time)) * 24 * 60 AS INTEGER) AS duration_minutes
                FROM sleep_session
                WHERE status = 'closed'
                  AND sleep_time IS NOT NULL
                  AND wake_time IS NOT NULL
                  AND wake_time >= sleep_time
                  {user_filter_sql}
                  {auto_fill_filter_sql}
            ) t
            WHERE t.stat_date BETWEEN ? AND ?
            ORDER BY datetime(t.sleep_time) DESC, t.id DESC
        """
        return await self._fetch_all(sql, tuple(params))

    async def count_orphan_morning_events(
        self,
        *,
        user_id: str | None,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
    ) -> int:
        user_filter_sql = ""
        params: list[Any] = [day_boundary_hour]
        if user_id:
            user_filter_sql = " AND user_id = ? "
            params.append(user_id)
        params.extend([start_date, end_date])
        sql = f"""
            SELECT COUNT(1) AS cnt
            FROM (
                SELECT
                    CASE
                        WHEN CAST(strftime('%H', event_time) AS INTEGER) < ?
                        THEN date(event_time, '-1 day')
                        ELSE date(event_time)
                    END AS stat_date
                FROM sleep_event
                WHERE event_type = 'good_morning'
                  AND event_status = 'orphan'
                  {user_filter_sql}
            ) t
            WHERE t.stat_date BETWEEN ? AND ?
        """
        row = await self._fetch_one(sql, tuple(params))
        return int((row or {}).get("cnt", 0))

    async def query_daily_sleep_minutes(
        self,
        *,
        user_id: str | None,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
    ) -> list[dict[str, Any]]:
        user_filter_sql = ""
        auto_fill_filter_sql = ""
        params: list[Any] = [day_boundary_hour]
        if user_id:
            user_filter_sql = " AND user_id = ? "
            params.append(user_id)
        if not include_auto_fill:
            auto_fill_filter_sql = " AND is_auto_filled = 0 "
        params.extend([start_date, end_date])
        sql = f"""
            SELECT stat_date, SUM(duration_minutes) AS total_minutes, COUNT(1) AS session_count
            FROM (
                SELECT
                    CASE
                        WHEN CAST(strftime('%H', sleep_time) AS INTEGER) < ?
                        THEN date(sleep_time, '-1 day')
                        ELSE date(sleep_time)
                    END AS stat_date,
                    CAST((JULIANDAY(wake_time) - JULIANDAY(sleep_time)) * 24 * 60 AS INTEGER) AS duration_minutes
                FROM sleep_session
                WHERE status = 'closed'
                  AND sleep_time IS NOT NULL
                  AND wake_time IS NOT NULL
                  AND wake_time >= sleep_time
                  {user_filter_sql}
                  {auto_fill_filter_sql}
            ) t
            WHERE stat_date BETWEEN ? AND ?
            GROUP BY stat_date
            ORDER BY stat_date ASC
        """
        return await self._fetch_all(sql, tuple(params))

    async def query_daily_group_metrics(
        self,
        *,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
    ) -> list[dict[str, Any]]:
        auto_fill_filter_sql = ""
        params: list[Any] = [day_boundary_hour]
        if not include_auto_fill:
            auto_fill_filter_sql = " AND is_auto_filled = 0 "
        params.extend([start_date, end_date])
        sql = f"""
            SELECT
                stat_date,
                SUM(duration_minutes) AS total_minutes,
                COUNT(1) AS session_count,
                COUNT(DISTINCT user_id) AS active_user_count
            FROM (
                SELECT
                    user_id,
                    CASE
                        WHEN CAST(strftime('%H', sleep_time) AS INTEGER) < ?
                        THEN date(sleep_time, '-1 day')
                        ELSE date(sleep_time)
                    END AS stat_date,
                    CAST((JULIANDAY(wake_time) - JULIANDAY(sleep_time)) * 24 * 60 AS INTEGER) AS duration_minutes
                FROM sleep_session
                WHERE status = 'closed'
                  AND sleep_time IS NOT NULL
                  AND wake_time IS NOT NULL
                  AND wake_time >= sleep_time
                  {auto_fill_filter_sql}
            ) t
            WHERE stat_date BETWEEN ? AND ?
            GROUP BY stat_date
            ORDER BY stat_date ASC
        """
        return await self._fetch_all(sql, tuple(params))

    async def query_active_user_count(
        self,
        *,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
    ) -> int:
        auto_fill_filter_sql = ""
        params: list[Any] = [day_boundary_hour]
        if not include_auto_fill:
            auto_fill_filter_sql = " AND is_auto_filled = 0 "
        params.extend([start_date, end_date])
        sql = f"""
            SELECT COUNT(DISTINCT user_id) AS cnt
            FROM (
                SELECT
                    user_id,
                    CASE
                        WHEN CAST(strftime('%H', sleep_time) AS INTEGER) < ?
                        THEN date(sleep_time, '-1 day')
                        ELSE date(sleep_time)
                    END AS stat_date
                FROM sleep_session
                WHERE status = 'closed'
                  AND sleep_time IS NOT NULL
                  AND wake_time IS NOT NULL
                  AND wake_time >= sleep_time
                  {auto_fill_filter_sql}
            ) t
            WHERE stat_date BETWEEN ? AND ?
        """
        row = await self._fetch_one(sql, tuple(params))
        return int((row or {}).get("cnt", 0))

    async def query_hourly_distribution(
        self,
        *,
        event: str,
        user_id: str | None,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
    ) -> list[dict[str, Any]]:
        column = "sleep_time" if event == "sleep" else "wake_time"
        user_filter_sql = ""
        auto_fill_filter_sql = ""
        params: list[Any] = [day_boundary_hour, day_boundary_hour]
        if user_id:
            user_filter_sql = " AND user_id = ? "
            params.append(user_id)
        if not include_auto_fill:
            auto_fill_filter_sql = " AND is_auto_filled = 0 "
        params.extend([start_date, end_date])
        sql = f"""
            SELECT
                stat_date,
                hour,
                COUNT(1) AS count
            FROM (
                SELECT
                    CASE
                        WHEN CAST(strftime('%H', {column}) AS INTEGER) < ?
                        THEN date({column}, '-1 day')
                        ELSE date({column})
                    END AS stat_date,
                    CASE
                        WHEN CAST(strftime('%H', {column}) AS INTEGER) < ?
                        THEN CAST(strftime('%H', {column}) AS INTEGER) + 24
                        ELSE CAST(strftime('%H', {column}) AS INTEGER)
                    END AS hour
                FROM sleep_session
                WHERE status = 'closed'
                  AND sleep_time IS NOT NULL
                  AND wake_time IS NOT NULL
                  AND wake_time >= sleep_time
                  AND {column} IS NOT NULL
                  {user_filter_sql}
                  {auto_fill_filter_sql}
            ) t
            WHERE stat_date BETWEEN ? AND ?
            GROUP BY stat_date, hour
            ORDER BY stat_date ASC, hour ASC
        """
        rows = await self._fetch_all(sql, tuple(params))
        normalized: list[dict[str, Any]] = []
        for row in rows:
            hour = int(row.get("hour") or 0) % 24
            normalized.append(
                {
                    "stat_date": row.get("stat_date"),
                    "hour": hour,
                    "count": int(row.get("count") or 0),
                }
            )
        return normalized

    async def query_leaderboard_activity(
        self,
        *,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        auto_fill_filter_sql = ""
        params: list[Any] = [
            day_boundary_hour,
            start_date,
            end_date,
            day_boundary_hour,
            start_date,
            end_date,
            day_boundary_hour,
            start_date,
            end_date,
            limit,
        ]
        if not include_auto_fill:
            auto_fill_filter_sql = " AND is_auto_filled = 0 "
        sql = f"""
            WITH event_stats AS (
                SELECT
                    user_id,
                    COUNT(1) AS activity_count,
                    MAX(event_time) AS last_event_time
                FROM sleep_event
                WHERE (
                    CASE
                        WHEN CAST(strftime('%H', event_time) AS INTEGER) < ?
                        THEN date(event_time, '-1 day')
                        ELSE date(event_time)
                    END
                ) BETWEEN ? AND ?
                GROUP BY user_id
            ),
            sleep_stats AS (
                SELECT
                    user_id,
                    SUM(duration_minutes) AS total_sleep_minutes,
                    COUNT(1) AS closed_count
                FROM (
                    SELECT
                        user_id,
                        CASE
                            WHEN CAST(strftime('%H', sleep_time) AS INTEGER) < ?
                            THEN date(sleep_time, '-1 day')
                            ELSE date(sleep_time)
                        END AS stat_date,
                        CAST((JULIANDAY(wake_time) - JULIANDAY(sleep_time)) * 24 * 60 AS INTEGER) AS duration_minutes
                    FROM sleep_session
                    WHERE status = 'closed'
                      AND sleep_time IS NOT NULL
                      AND wake_time IS NOT NULL
                      AND wake_time >= sleep_time
                      {auto_fill_filter_sql}
                ) t
                WHERE stat_date BETWEEN ? AND ?
                GROUP BY user_id
            ),
            users AS (
                SELECT user_id FROM event_stats
                UNION
                SELECT user_id FROM sleep_stats
            ),
            latest_events AS (
                SELECT
                    user_id,
                    MAX(event_time) AS latest_event_time
                FROM sleep_event
                WHERE (
                    CASE
                        WHEN CAST(strftime('%H', event_time) AS INTEGER) < ?
                        THEN date(event_time, '-1 day')
                        ELSE date(event_time)
                    END
                ) BETWEEN ? AND ?
                GROUP BY user_id
            )
            SELECT
                u.user_id AS user_id,
                COALESCE(e.activity_count, 0) AS activity_count,
                COALESCE(s.total_sleep_minutes, 0) AS total_sleep_minutes,
                CASE
                    WHEN COALESCE(s.closed_count, 0) = 0 THEN 0
                    ELSE CAST(COALESCE(s.total_sleep_minutes, 0) / s.closed_count AS INTEGER)
                END AS avg_sleep_minutes,
                l.latest_event_time AS last_event_time
            FROM users u
            LEFT JOIN event_stats e ON e.user_id = u.user_id
            LEFT JOIN sleep_stats s ON s.user_id = u.user_id
            LEFT JOIN latest_events l ON l.user_id = u.user_id
            ORDER BY activity_count DESC, total_sleep_minutes DESC, datetime(last_event_time) DESC
            LIMIT ?
        """
        rows = await self._fetch_all(sql, tuple(params))
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "user_id": row.get("user_id"),
                    "activity_count": int(row.get("activity_count") or 0),
                    "total_sleep_minutes": int(row.get("total_sleep_minutes") or 0),
                    "avg_sleep_minutes": int(row.get("avg_sleep_minutes") or 0),
                    "last_event_time": row.get("last_event_time"),
                }
            )
        return result

    async def query_user_overview(
        self,
        *,
        user_id: str,
        start_date: str,
        end_date: str,
        day_boundary_hour: int,
        include_auto_fill: bool,
    ) -> dict[str, Any]:
        records = await self.query_closed_sessions_for_stats(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        daily = await self.query_daily_sleep_minutes(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        sleep_rows = await self.query_hourly_distribution(
            event="sleep",
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        wake_rows = await self.query_hourly_distribution(
            event="wake",
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=day_boundary_hour,
            include_auto_fill=include_auto_fill,
        )
        user_sleep_rows = [row for row in sleep_rows if row.get("stat_date")]
        user_wake_rows = [row for row in wake_rows if row.get("stat_date")]
        open_count = await self.get_open_session_count(user_id=user_id)
        orphan_count = await self.count_orphan_morning_events(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=day_boundary_hour,
        )
        return {
            "records": records,
            "daily_series": daily,
            "sleep_heatmap": user_sleep_rows,
            "wake_heatmap": user_wake_rows,
            "open_session_count": open_count,
            "orphan_morning_count": orphan_count,
        }
