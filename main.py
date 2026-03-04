from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from quart import jsonify, request

import astrbot.api.event.filter as filter
from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import llm_tool
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register

from .app.config import PluginSettings, load_plugin_settings
from .app.repository import OyasumiRepository
from .app.response_service import ResponseService
from .app.session_service import SessionService
from .app.snapshot_service import SnapshotService
from .app.standalone_webui import StandaloneWebUIServer
from .app.stats_service import StatsService, resolve_date_range, validate_date_text
from .app.trigger_matcher import TriggerMatcher

PLUGIN_NAME = "astrbot_plugin_oyasumi"


def _resolve_plugin_data_dir(plugin_name: str) -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

        return Path(get_astrbot_plugin_data_path()) / plugin_name
    except Exception:
        return Path(StarTools.get_data_dir(plugin_name))


@register(
    "astrbot_plugin_oyasumi",
    "RichardLiu",
    "基于正则触发的早安晚安会话追踪插件，支持统计、修正与个性化分析。",
    "v0.1.0",
)
class OyasumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.context = context
        self.config = dict(config or {})

        plugin_data_dir = _resolve_plugin_data_dir(PLUGIN_NAME)
        sql_path = Path(__file__).parent / "app" / "sql" / "init.sql"
        self.settings: PluginSettings = load_plugin_settings(
            self.config,
            PLUGIN_NAME,
            plugin_data_dir=plugin_data_dir,
            sql_init_path=sql_path,
        )

        self.repository = OyasumiRepository(
            db_path=self.settings.db_path,
            init_sql_path=self.settings.sql_init_path,
        )
        self.trigger_matcher = TriggerMatcher(self.settings)
        self.session_service = SessionService(self.repository, self.settings)
        self.stats_service = StatsService(self.repository, self.settings)
        self.response_service = ResponseService(self.context, self.settings)
        self.response_service.bind_repository(self.repository)
        self.snapshot_service = SnapshotService(self.settings.snapshot_path)
        self.standalone_webui_server: StandaloneWebUIServer | None = None

    async def initialize(self) -> None:
        await self.repository.initialize()
        self._register_web_apis()
        if self.settings.standalone_webui_enabled:
            self.standalone_webui_server = StandaloneWebUIServer(self)
            await self.standalone_webui_server.start()
            logger.info(
                "[oyasumi] standalone webui started at http://%s:%s",
                self.settings.standalone_webui_host,
                self.settings.standalone_webui_port,
            )
        logger.info(
            "[oyasumi] initialized, db=%s, enabled=%s",
            self.settings.db_path,
            self.settings.enabled,
        )

    async def terminate(self) -> None:
        if self.standalone_webui_server is not None:
            await self.standalone_webui_server.stop()
            self.standalone_webui_server = None
        await self.repository.close()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.settings.enabled:
            return

        text = (event.message_str or "").strip()
        if not text:
            return
        if text.startswith("/"):
            return

        match_result = self.trigger_matcher.match(text)
        if match_result is None:
            return

        user_id = str(event.get_sender_id())
        user_name = (event.get_sender_name() or user_id).strip() or user_id
        now = datetime.now()
        umo = getattr(event, "unified_msg_origin", "") or user_id

        process_result = await self.session_service.process_event(
            user_id=user_id,
            event_type=match_result.event_type,
            event_time=now,
            raw_message=text,
            matched_pattern=match_result.matched_pattern,
        )

        reply = await self.response_service.build_event_reply(
            umo=umo,
            user_id=user_id,
            user_name=user_name,
            result=process_result,
        )
        dashboard = await self.stats_service.build_dashboard(
            user_id=user_id, recent_days=7
        )
        snapshot_payload = self.snapshot_service.build_event_snapshot(
            user_id=user_id,
            dashboard=dashboard,
            last_action=process_result.action,
        )
        self.snapshot_service.safe_write(snapshot_payload)

        if reply:
            yield event.plain_result(reply)

    @filter.command_group("作息", alias={"sleep", "oyasumi"})
    async def oyasumi(self, event: AstrMessageEvent):
        """作息插件命令入口"""
        yield event.plain_result(
            "作息插件命令：\n"
            "/作息 状态\n"
            "/作息 看板 [days]\n"
            "/作息 统计 [start_date] [end_date] [target_user_id]\n"
            "/作息 分析 [start_date] [end_date] [target_user_id]\n"
            "/作息 会话 [limit] [target_user_id]\n"
            "/作息 修正 <session_id> [sleep_time] [wake_time]\n"
            "时间格式：YYYY-MM-DD 或 YYYY-MM-DDTHH:MM[:SS]"
        )

    @oyasumi.command("状态", alias={"status"})
    async def status(self, event: AstrMessageEvent):
        """查看插件运行状态"""
        open_count = await self.repository.get_open_session_count(
            user_id=str(event.get_sender_id())
        )
        yield event.plain_result(
            f"插件启用：{self.settings.enabled}\n"
            f"回复模式：{self.settings.reply_mode}\n"
            f"当前用户进行中会话：{open_count}\n"
            f"数据库路径：{self.settings.db_path}"
        )

    @oyasumi.command("看板", alias={"dashboard"})
    async def dashboard(self, event: AstrMessageEvent, days: int = 7):
        """查看最近作息看板"""
        user_id = str(event.get_sender_id())
        days = max(1, min(days, 60))
        data = await self.stats_service.build_dashboard(
            user_id=user_id, recent_days=days
        )
        lines = [
            f"用户：{user_id}",
            f"区间：{data['start_date']} ~ {data['end_date']}",
            f"总时长：{data['total_sleep_minutes']} 分钟",
            f"平均时长：{data['avg_sleep_minutes']} 分钟",
            f"进行中会话：{data['open_session_count']}",
            "每日趋势：",
        ]
        daily = data.get("daily") or []
        if not daily:
            lines.append("- 暂无数据")
        else:
            for row in daily:
                lines.append(
                    f"- {row['stat_date']} | 总时长 {row['total_minutes']} 分钟 | 会话 {row['session_count']}"
                )
        yield event.plain_result("\n".join(lines))

    @oyasumi.command("统计", alias={"stats"})
    async def stats(
        self,
        event: AstrMessageEvent,
        start_date: str = "",
        end_date: str = "",
        target_user_id: str = "",
    ):
        """查询睡眠统计"""
        resolved_start, resolved_end = resolve_date_range(start_date, end_date)
        if not validate_date_text(resolved_start) or not validate_date_text(
            resolved_end
        ):
            yield event.plain_result("日期格式错误，请使用 YYYY-MM-DD。")
            return

        target_user, can_query_other = self._resolve_target_user(event, target_user_id)
        if not can_query_other and target_user_id:
            yield event.plain_result("当前配置仅管理员可查询他人数据。")
            return
        summary = await self.stats_service.build_summary(
            user_id=target_user,
            start_date=resolved_start,
            end_date=resolved_end,
        )
        yield event.plain_result(summary.to_text())

    @oyasumi.command("分析", alias={"analysis"})
    async def analysis(
        self,
        event: AstrMessageEvent,
        start_date: str = "",
        end_date: str = "",
        target_user_id: str = "",
    ):
        """生成个性化分析"""
        resolved_start, resolved_end = resolve_date_range(start_date, end_date)
        if not validate_date_text(resolved_start) or not validate_date_text(
            resolved_end
        ):
            yield event.plain_result("日期格式错误，请使用 YYYY-MM-DD。")
            return

        target_user, can_query_other = self._resolve_target_user(event, target_user_id)
        if not can_query_other and target_user_id:
            yield event.plain_result("当前配置仅管理员可查询他人数据。")
            return
        summary = await self.stats_service.build_summary(
            user_id=target_user,
            start_date=resolved_start,
            end_date=resolved_end,
        )
        stats_text = summary.to_text()
        reply = await self.response_service.build_analysis_reply(
            umo=getattr(event, "unified_msg_origin", "") or str(event.get_sender_id()),
            user_name=(event.get_sender_name() or str(event.get_sender_id())).strip()
            or str(event.get_sender_id()),
            stats_text=stats_text,
        )
        yield event.plain_result(reply)

    @oyasumi.command("会话", alias={"sessions"})
    async def sessions(
        self,
        event: AstrMessageEvent,
        limit: int = 10,
        target_user_id: str = "",
    ):
        """查看最近会话"""
        limit = max(1, min(limit, 50))
        target_user, can_query_other = self._resolve_target_user(event, target_user_id)
        if not can_query_other and target_user_id:
            yield event.plain_result("当前配置仅管理员可查询他人数据。")
            return
        rows = await self.repository.list_sessions(user_id=target_user, limit=limit)
        if not rows:
            yield event.plain_result("暂无会话记录。")
            return
        lines = [f"最近 {len(rows)} 条会话："]
        for row in rows:
            lines.append(
                f"#{row['id']} | 用户:{row['user_id']} | 状态:{row['status']} | "
                f"入睡:{row['sleep_time'] or '-'} | 醒来:{row['wake_time'] or '-'} | "
                f"时长:{row['duration_minutes'] if row['duration_minutes'] is not None else '-'}分钟"
            )
        yield event.plain_result("\n".join(lines))

    @oyasumi.command("修正", alias={"fix", "update"})
    async def fix_session(
        self,
        event: AstrMessageEvent,
        session_id: int,
        sleep_time: str = "",
        wake_time: str = "",
    ):
        """修正会话时间"""
        reply = await self.session_service.update_session_by_command(
            actor_user_id=str(event.get_sender_id()),
            is_admin=self._is_admin(event),
            session_id=session_id,
            sleep_time_str=sleep_time or None,
            wake_time_str=wake_time or None,
        )
        yield event.plain_result(reply)

    @llm_tool(name="oyasumi_sleep_stats")
    async def oyasumi_sleep_stats(
        self,
        event: AstrMessageEvent,
        start_date: str = "",
        end_date: str = "",
        target_user_id: str = "",
    ) -> str:
        """给大模型提供睡眠统计数据"""
        resolved_start, resolved_end = resolve_date_range(start_date, end_date)
        if not validate_date_text(resolved_start) or not validate_date_text(
            resolved_end
        ):
            return "日期格式错误，请使用 YYYY-MM-DD。"

        target_user, can_query_other = self._resolve_target_user(event, target_user_id)
        if not can_query_other and target_user_id:
            return "当前配置仅管理员可查询他人数据，已回退为查询当前用户。"
        summary = await self.stats_service.build_summary(
            user_id=target_user,
            start_date=resolved_start,
            end_date=resolved_end,
        )
        return summary.to_text(include_records_limit=20)

    @llm_tool(name="oyasumi_sleep_analysis")
    async def oyasumi_sleep_analysis(
        self,
        event: AstrMessageEvent,
        start_date: str = "",
        end_date: str = "",
        target_user_id: str = "",
    ) -> str:
        """给大模型提供睡眠分析结果"""
        stats_text = await self.oyasumi_sleep_stats(
            event=event,
            start_date=start_date,
            end_date=end_date,
            target_user_id=target_user_id,
        )
        if "日期格式错误" in stats_text:
            return stats_text
        return await self.response_service.build_analysis_reply(
            umo=getattr(event, "unified_msg_origin", "") or str(event.get_sender_id()),
            user_name=(event.get_sender_name() or str(event.get_sender_id())).strip()
            or str(event.get_sender_id()),
            stats_text=stats_text,
        )

    def _register_web_apis(self) -> None:
        self.context.register_web_api(
            "/oyasumi/users",
            self.webui_users_api,
            ["GET"],
            "List user ids for Oyasumi dashboard",
        )
        self.context.register_web_api(
            "/oyasumi/dashboard",
            self.webui_dashboard_api,
            ["GET"],
            "Get dashboard data for Oyasumi",
        )
        self.context.register_web_api(
            "/oyasumi/sessions",
            self.webui_sessions_api,
            ["GET"],
            "Get recent sessions for Oyasumi",
        )
        self.context.register_web_api(
            "/oyasumi/summary",
            self.webui_summary_api,
            ["GET"],
            "Get summary stats for Oyasumi",
        )
        self.context.register_web_api(
            "/oyasumi/analysis",
            self.webui_analysis_api,
            ["POST"],
            "Generate analysis text for Oyasumi",
        )
        self.context.register_web_api(
            "/oyasumi/snapshot",
            self.webui_snapshot_api,
            ["GET"],
            "Get latest Oyasumi snapshot",
        )
        self.context.register_web_api(
            "/oyasumi/overview",
            self.webui_overview_api,
            ["GET"],
            "Get group overview data for Oyasumi",
        )
        self.context.register_web_api(
            "/oyasumi/leaderboard",
            self.webui_leaderboard_api,
            ["GET"],
            "Get activity leaderboard data for Oyasumi",
        )
        self.context.register_web_api(
            "/oyasumi/user_insight",
            self.webui_user_insight_api,
            ["GET"],
            "Get user insight data for Oyasumi",
        )

    async def webui_users_api(self):
        limit = self._safe_int(
            request.args.get("limit"), default=200, minimum=1, maximum=1000
        )
        user_ids = await self.repository.list_user_ids(limit=limit)
        return jsonify({"status": "ok", "data": {"user_ids": user_ids}})

    async def webui_dashboard_api(self):
        user_id = (request.args.get("user_id", "") or "").strip() or None
        days = self._safe_int(
            request.args.get("days"), default=7, minimum=1, maximum=60
        )
        data = await self._build_dashboard_data(user_id=user_id, recent_days=days)
        return jsonify({"status": "ok", "data": data})

    async def webui_sessions_api(self):
        user_id = (request.args.get("user_id", "") or "").strip() or None
        limit = self._safe_int(
            request.args.get("limit"), default=20, minimum=1, maximum=100
        )
        rows = await self.repository.list_sessions(user_id=user_id, limit=limit)
        return jsonify({"status": "ok", "data": {"sessions": rows}})

    async def webui_summary_api(self):
        user_id = (request.args.get("user_id", "") or "").strip() or None
        start_date = (request.args.get("start_date", "") or "").strip()
        end_date = (request.args.get("end_date", "") or "").strip()
        resolved_start, resolved_end = resolve_date_range(start_date, end_date)
        if not validate_date_text(resolved_start) or not validate_date_text(
            resolved_end
        ):
            return jsonify(
                {
                    "status": "error",
                    "message": "Invalid date format, expected YYYY-MM-DD",
                }
            )

        summary = await self.stats_service.build_summary(
            user_id=user_id,
            start_date=resolved_start,
            end_date=resolved_end,
        )
        return jsonify(
            {
                "status": "ok",
                "data": {
                    "user_id": summary.user_id,
                    "start_date": summary.start_date,
                    "end_date": summary.end_date,
                    "total_sessions": summary.total_sessions,
                    "total_sleep_minutes": summary.total_sleep_minutes,
                    "avg_sleep_minutes": summary.avg_sleep_minutes,
                    "earliest_sleep_time": summary.earliest_sleep_time,
                    "latest_sleep_time": summary.latest_sleep_time,
                    "earliest_wake_time": summary.earliest_wake_time,
                    "latest_wake_time": summary.latest_wake_time,
                    "open_session_count": summary.open_session_count,
                    "orphan_morning_count": summary.orphan_morning_count,
                    "records": summary.records,
                },
            }
        )

    async def webui_analysis_api(self):
        payload = await request.get_json(silent=True) or {}
        user_id = (payload.get("user_id", "") or "").strip() or None
        start_date = (payload.get("start_date", "") or "").strip()
        end_date = (payload.get("end_date", "") or "").strip()

        resolved_start, resolved_end = resolve_date_range(start_date, end_date)
        if not validate_date_text(resolved_start) or not validate_date_text(
            resolved_end
        ):
            return jsonify(
                {
                    "status": "error",
                    "message": "Invalid date format, expected YYYY-MM-DD",
                }
            )

        summary = await self.stats_service.build_summary(
            user_id=user_id,
            start_date=resolved_start,
            end_date=resolved_end,
        )
        stats_text = summary.to_text(include_records_limit=20)
        (
            analysis_text,
            used_llm,
            llm_reason,
        ) = await self.response_service.build_analysis_reply_with_meta(
            umo=(payload.get("umo") or "oyasumi_webui"),
            user_name=(payload.get("user_name") or user_id or "webui_user"),
            stats_text=stats_text,
        )

        return jsonify(
            {
                "status": "ok",
                "data": {
                    "analysis_text": analysis_text,
                    "stats_text": stats_text,
                    "used_llm": used_llm,
                    "llm_reason": llm_reason,
                    "start_date": resolved_start,
                    "end_date": resolved_end,
                },
            }
        )

    async def webui_snapshot_api(self):
        if not self.settings.snapshot_path.exists():
            return jsonify({"status": "ok", "data": {"snapshot": None}})
        try:
            snapshot = self.settings.snapshot_path.read_text(encoding="utf-8")
            payload = json.loads(snapshot)
        except Exception as exc:
            return jsonify({"status": "error", "message": str(exc)})
        return jsonify({"status": "ok", "data": {"snapshot": payload}})

    async def webui_overview_api(self):
        start_date, end_date, error = self._resolve_web_date_range(
            days_value=request.args.get("days"),
            start_date=(request.args.get("start_date", "") or "").strip(),
            end_date=(request.args.get("end_date", "") or "").strip(),
        )
        if error:
            return jsonify({"status": "error", "message": error})

        data = await self.stats_service.build_group_overview(
            start_date=start_date,
            end_date=end_date,
        )
        return jsonify({"status": "ok", "data": data})

    async def webui_leaderboard_api(self):
        start_date, end_date, error = self._resolve_web_date_range(
            days_value=request.args.get("days"),
            start_date=(request.args.get("start_date", "") or "").strip(),
            end_date=(request.args.get("end_date", "") or "").strip(),
        )
        if error:
            return jsonify({"status": "error", "message": error})

        limit = self._safe_int(
            request.args.get("limit"),
            default=10,
            minimum=1,
            maximum=100,
        )
        metric = (request.args.get("metric", "activity") or "activity").strip().lower()
        data = await self.stats_service.build_leaderboard(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            metric=metric,
        )
        return jsonify({"status": "ok", "data": data})

    async def webui_user_insight_api(self):
        user_id = (request.args.get("user_id", "") or "").strip()
        if not user_id:
            return jsonify({"status": "error", "message": "user_id is required"})

        start_date, end_date, error = self._resolve_web_date_range(
            days_value=request.args.get("days"),
            start_date=(request.args.get("start_date", "") or "").strip(),
            end_date=(request.args.get("end_date", "") or "").strip(),
        )
        if error:
            return jsonify({"status": "error", "message": error})

        data = await self.stats_service.build_user_insight(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
        )
        return jsonify({"status": "ok", "data": data})

    async def _build_dashboard_data(
        self,
        *,
        user_id: str | None,
        recent_days: int,
    ) -> dict[str, Any]:
        if user_id:
            return await self.stats_service.build_dashboard(
                user_id=user_id,
                recent_days=recent_days,
            )

        today = date.today()
        start_date_obj = today - timedelta(days=max(1, recent_days) - 1)
        start_date = start_date_obj.strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        daily = await self.repository.query_daily_sleep_minutes(
            user_id=None,
            start_date=start_date,
            end_date=end_date,
            day_boundary_hour=self.settings.day_boundary_hour,
            include_auto_fill=self.settings.include_auto_fill_in_stats,
        )
        total_minutes = sum(int(row.get("total_minutes") or 0) for row in daily)
        total_sessions = sum(int(row.get("session_count") or 0) for row in daily)
        avg_minutes = int(total_minutes / total_sessions) if total_sessions else 0
        open_count = await self.repository.get_open_session_count(user_id=None)
        return {
            "user_id": None,
            "start_date": start_date,
            "end_date": end_date,
            "open_session_count": open_count,
            "total_sleep_minutes": total_minutes,
            "avg_sleep_minutes": avg_minutes,
            "daily": daily,
        }

    @staticmethod
    def _safe_int(
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(parsed, maximum))

    def _resolve_web_date_range(
        self,
        *,
        days_value: Any,
        start_date: str,
        end_date: str,
        default_days: int = 7,
        max_days: int = 90,
    ) -> tuple[str, str, str | None]:
        if start_date or end_date:
            resolved_start, resolved_end = resolve_date_range(start_date, end_date)
            if not validate_date_text(resolved_start) or not validate_date_text(
                resolved_end
            ):
                return "", "", "Invalid date format, expected YYYY-MM-DD"
            start_obj = datetime.strptime(resolved_start, "%Y-%m-%d").date()
            end_obj = datetime.strptime(resolved_end, "%Y-%m-%d").date()
            if end_obj < start_obj:
                return "", "", "end_date must be greater than or equal to start_date"
            if (end_obj - start_obj).days + 1 > max_days:
                return "", "", f"Date range cannot exceed {max_days} days"
            return resolved_start, resolved_end, None

        days = self._safe_int(
            days_value,
            default=default_days,
            minimum=1,
            maximum=max_days,
        )
        today = date.today()
        start_obj = today - timedelta(days=days - 1)
        return (
            start_obj.strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
            None,
        )

    def _resolve_target_user(
        self, event: AstrMessageEvent, target_user_id: str
    ) -> tuple[str | None, bool]:
        sender_id = str(event.get_sender_id())
        if not target_user_id:
            return sender_id, True
        if target_user_id == sender_id:
            return sender_id, True
        if self.settings.admin_only_global_query and not self._is_admin(event):
            return sender_id, False
        return target_user_id, True

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        is_admin_callable = getattr(event, "is_admin", None)
        if callable(is_admin_callable):
            try:
                return bool(is_admin_callable())
            except Exception:
                return False
        return False
