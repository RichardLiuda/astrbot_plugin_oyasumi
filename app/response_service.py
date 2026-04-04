from __future__ import annotations

import asyncio
import random
from datetime import date
from typing import TYPE_CHECKING, Any

from astrbot.api import logger
from astrbot.api.star import Context

from .config import PluginSettings
from .session_service import EventProcessResult
from .trigger_matcher import EVENT_GOOD_NIGHT

if TYPE_CHECKING:
    from .repository import OyasumiRepository


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class ResponseService:
    _CATGIRL_EXTRAS: dict[str, list[str]] = {
        "morning": [
            "今天也要元气满满，喵~",
            "先喝口水再出发会更舒服喵~",
            "你认真记录作息的样子超可爱，喵呜~",
            "记得拉开窗帘晒晒太阳，喵~",
        ],
        "night": [
            "把烦恼放下，安心睡吧，喵~",
            "记得盖好小被子，晚安喵~",
            "本猫娘会帮你继续盯作息，喵~",
            "今晚做个甜甜的梦，喵呜~",
        ],
        "orphan": [
            "补一条记录我就能算得更准啦，喵~",
            "要不要现在补录一下呀，喵~",
            "不急，我们慢慢把记录补完整，喵~",
        ],
        "duplicate": [
            "这边已经帮你处理好重复记录啦，喵~",
            "别担心，我会继续守着你的作息本本，喵~",
            "记录还在进行中，我会好好看着它，喵~",
        ],
        "default": [
            "我会一直温柔地陪你记作息，喵~",
            "有我在，作息打卡会越来越稳，喵~",
            "保持一点点进步就很棒啦，喵~",
        ],
    }

    def __init__(self, context: Context, settings: PluginSettings):
        self.context = context
        self.settings = settings
        self.repository: OyasumiRepository | None = None

    def bind_repository(self, repository: OyasumiRepository) -> None:
        self.repository = repository

    async def build_event_reply(
        self,
        *,
        umo: str,
        user_id: str,
        user_name: str,
        result: EventProcessResult,
    ) -> str:
        if self.settings.reply_mode == "llm" and self.settings.llm_enabled:
            llm_reply = await self._generate_event_reply_llm(
                umo=umo,
                user_id=user_id,
                user_name=user_name,
                result=result,
            )
            if llm_reply:
                return llm_reply
            if not self.settings.llm_fallback_to_static:
                return "已记录事件，但大模型回复暂不可用。"
        return self._build_event_reply_static(user_name=user_name, result=result)

    async def build_analysis_reply(
        self,
        *,
        umo: str,
        user_name: str,
        stats_text: str,
    ) -> str:
        text, _used_llm, _reason = await self.build_analysis_reply_with_meta(
            umo=umo,
            user_name=user_name,
            stats_text=stats_text,
        )
        return text

    async def build_analysis_reply_with_meta(
        self,
        *,
        umo: str,
        user_name: str,
        stats_text: str,
    ) -> tuple[str, bool, str]:
        provider_id = self._resolve_analysis_provider_id(umo)
        if not provider_id:
            return ("未找到可用模型，无法生成分析。", False, "provider_not_found")

        is_group_analysis = (
            user_name == "全体成员" or "统计对象：全体成员综合分析" in stats_text
        )
        target_label = "分析对象" if is_group_analysis else "用户昵称"
        radar_focus = (
            "成员分布、整体节律稳定性、群体晚睡倾向、补觉迹象"
            if is_group_analysis
            else "节律稳定性、晚睡倾向、补觉迹象"
        )
        action_focus = (
            "面向群聊全体成员给出3条可执行建议"
            if is_group_analysis
            else "给出3条可执行建议"
        )

        prompt = (
            f"{target_label}：{user_name}\n"
            f"睡眠统计数据：\n{stats_text}\n\n"
            "请按以下规则输出 Markdown：\n"
            "1. 语气贴近二次元群聊，轻松、有梗、友好，不要冒犯或阴阳怪气。\n"
            "2. 使用标题结构：`## 作息播报`、`## 规律雷达`、`## 明日行动清单`。\n"
            "3. 在“作息播报”中给出一句总结和1-2个关键数字。\n"
            f"4. 在“规律雷达”中点评{radar_focus}。\n"
            f"5. 在“明日行动清单”中{action_focus}，用有序列表输出。\n"
            "6. 允许少量 ACG 风格词汇或颜文字，但保持信息密度，避免过度玩梗。\n"
            "7. 结尾补一句简短鼓励，不要超过20字。"
        )

        system_prompt = await self._build_analysis_system_prompt(umo)
        llm_text = await self._call_llm(
            provider_id=provider_id,
            system_prompt=system_prompt,
            prompt=prompt,
            scene="analysis",
        )
        if llm_text:
            return llm_text, True, "ok"
        return ("大模型分析失败。", False, "llm_failed")

    def _build_event_reply_static(
        self,
        *,
        user_name: str,
        result: EventProcessResult,
    ) -> str:
        data: dict[str, Any] = {
            "user_name": user_name,
            "sleep_time": result.sleep_time or "-",
            "wake_time": result.wake_time or "-",
            "duration_human": self._format_duration_text(result.duration_minutes),
            "duration_minutes": (
                str(result.duration_minutes)
                if result.duration_minutes is not None
                else "-"
            ),
            "open_session_count": str(result.open_session_count),
            "abandoned_count": str(result.abandoned_count),
        }

        if result.event_type == EVENT_GOOD_NIGHT:
            if result.action == "night_duplicate_ignored":
                text = self._render_template(self.settings.duplicate_night_reply, data)
                return self._apply_catgirl_tone(text, style="duplicate")
            base_text = self._render_template(self.settings.night_static_reply, data)
            return self._apply_catgirl_tone(base_text, style="night")

        if result.orphaned and not result.auto_filled:
            text = self._render_template(self.settings.orphan_morning_reply, data)
            return self._apply_catgirl_tone(text, style="orphan")

        base_text = self._render_template(self.settings.morning_static_reply, data)
        return self._apply_catgirl_tone(base_text, style="morning")

    @staticmethod
    def _format_duration_text(duration_minutes: int | None) -> str:
        if duration_minutes is None:
            return "-"
        if duration_minutes < 60:
            return f"{duration_minutes}分钟"

        hours, minutes = divmod(duration_minutes, 60)
        if minutes == 0:
            return f"{hours}小时"
        if minutes < 5:
            return f"约{hours}小时"
        return f"{hours}小时{minutes}分钟"

    async def _build_analysis_system_prompt(self, umo: str) -> str:
        base_prompt = (self.settings.llm_prompt_analysis or "").strip()
        persona_prompt = await self._get_persona_prompt(umo)
        if not persona_prompt:
            return base_prompt
        return (
            f"{persona_prompt}\n\n"
            "# Oyasumi Analysis Task\n"
            f"{base_prompt}\n"
            "你必须保持与当前人格一致的语气、措辞与角色边界。"
        )

    async def _get_persona_prompt(self, umo: str) -> str:
        persona_mgr = getattr(self.context, "persona_manager", None)
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if persona_mgr is None:
            return ""

        try:
            conversation_persona_id = None
            if conv_mgr is not None:
                curr_cid = await conv_mgr.get_curr_conversation_id(umo)
                if curr_cid:
                    conversation = await conv_mgr.get_conversation(umo, curr_cid)
                    conversation_persona_id = getattr(conversation, "persona_id", None)
                    if conversation_persona_id and conversation_persona_id != "[%None]":
                        persona = await persona_mgr.get_persona(conversation_persona_id)
                        prompt = (getattr(persona, "system_prompt", "") or "").strip()
                        if prompt:
                            return prompt

            provider_settings: dict[str, Any] = {}
            try:
                conf = self.context.get_config(umo)
                if hasattr(conf, "get"):
                    provider_settings = conf.get("provider_settings", {}) or {}
            except Exception:
                pass

            platform_name = str(umo).split(":", 1)[0] if ":" in str(umo) else ""
            (
                _persona_id,
                selected_persona,
                _force_id,
                _is_webchat_special,
            ) = await persona_mgr.resolve_selected_persona(
                umo=umo,
                conversation_persona_id=conversation_persona_id,
                platform_name=platform_name,
                provider_settings=provider_settings,
            )
            if isinstance(selected_persona, dict):
                prompt = (selected_persona.get("prompt") or "").strip()
                if prompt:
                    return prompt

            default_persona = await persona_mgr.get_default_persona_v3(umo)
            if isinstance(default_persona, dict):
                return (default_persona.get("prompt") or "").strip()
        except Exception as exc:
            logger.warning("[oyasumi] failed to resolve persona prompt: %s", exc)
        return ""

    def _apply_catgirl_tone(self, text: str, *, style: str = "default") -> str:
        """Make static replies livelier in a gentle catgirl style."""
        cleaned = (text or "").strip()
        if not cleaned:
            cleaned = "收到啦，我会帮你记好作息"

        if not getattr(self.settings, "append_catgirl_extra", True):
            return cleaned
        if "喵" not in cleaned:
            if cleaned.endswith(("。", "！", "？", ".", "!", "?", "~", "～")):
                cleaned = f"{cleaned} 喵~"
            else:
                cleaned = f"{cleaned}，喵~"


        pool = self._CATGIRL_EXTRAS.get(style) or self._CATGIRL_EXTRAS["default"]
        extra = random.choice(pool)
        if extra in cleaned:
            return cleaned
        return f"{cleaned}\n{extra}"

    async def _generate_event_reply_llm(
        self,
        *,
        umo: str,
        user_id: str,
        user_name: str,
        result: EventProcessResult,
    ) -> str | None:
        provider_id = self._resolve_reply_provider_id(umo)
        if not provider_id:
            return None

        if result.event_type == EVENT_GOOD_NIGHT:
            system_prompt = self.settings.llm_prompt_night
            action_text = "晚安事件"
        else:
            system_prompt = self.settings.llm_prompt_morning
            action_text = "早安事件"

        today_records_text = await self._build_sender_today_context(user_id)

        prompt = (
            f"用户昵称：{user_name}\n"
            f"用户ID：{user_id}\n"
            f"事件类型：{action_text}\n"
            f"动作结果：{result.action}\n"
            f"入睡时间：{result.sleep_time or '-'}\n"
            f"醒来时间：{result.wake_time or '-'}\n"
            f"时长（自然表达）：{self._format_duration_text(result.duration_minutes)}\n"
            f"时长（分钟）：{result.duration_minutes if result.duration_minutes is not None else '-'}\n"
            f"当日相关记录：\n{today_records_text}\n"
            "请结合上述当日记录，仅输出一段中文短回复：1-2句、总字数不超过50字。"
            "不要分点、不要标题、不要代码块、不要换行。"
            "语气温柔可爱，最多带一次“喵~”。"
        )
        logger.debug(
            "[oyasumi] event llm request | user_id=%s | event=%s | provider=%s | system_prompt_chars=%s | prompt_chars=%s",
            user_id,
            action_text,
            provider_id,
            len(system_prompt or ""),
            len(prompt or ""),
        )
        llm_text = await self._call_llm(
            provider_id=provider_id,
            system_prompt=system_prompt,
            prompt=prompt,
            scene="event_reply",
        )
        logger.debug(
            "[oyasumi] event llm response | user_id=%s | event=%s | has_reply=%s | reply_chars=%s",
            user_id,
            action_text,
            bool(llm_text),
            len(llm_text or ""),
        )
        return llm_text

    async def _build_sender_today_context(self, user_id: str) -> str:
        if not user_id:
            return "无用户标识，无法查询。"
        if self.repository is None:
            return "仓储未绑定，无法查询。"

        today = date.today().strftime("%Y-%m-%d")
        try:
            daily_rows = await self.repository.query_daily_sleep_minutes(
                user_id=user_id,
                start_date=today,
                end_date=today,
                day_boundary_hour=self.settings.day_boundary_hour,
                include_auto_fill=self.settings.include_auto_fill_in_stats,
            )
            closed_rows = await self.repository.query_closed_sessions_for_stats(
                user_id=user_id,
                start_date=today,
                end_date=today,
                day_boundary_hour=self.settings.day_boundary_hour,
                include_auto_fill=self.settings.include_auto_fill_in_stats,
            )
            recent_rows = await self.repository.list_sessions(user_id=user_id, limit=5)
            open_count = await self.repository.get_open_session_count(user_id=user_id)
        except Exception as exc:
            logger.warning("[oyasumi] failed to query today context: %s", exc)
            return "查询失败。"

        if daily_rows:
            daily = daily_rows[0]
            total_minutes = int(daily.get("total_minutes") or 0)
            session_count = int(daily.get("session_count") or 0)
        else:
            total_minutes = 0
            session_count = 0

        lines = [
            f"- 统计日期: {today}",
            f"- 当日闭合会话数: {session_count}",
            f"- 当日累计睡眠分钟: {total_minutes}",
            f"- 当前进行中会话数: {open_count}",
            "- 当日闭合会话明细:",
        ]

        if not closed_rows:
            lines.append("  - 无")
        else:
            for row in closed_rows[:5]:
                lines.append(
                    "  - "
                    f"#{row.get('id')} "
                    f"sleep={row.get('sleep_time') or '-'} "
                    f"wake={row.get('wake_time') or '-'} "
                    f"duration={row.get('duration_minutes') or 0}m"
                )

        lines.append("- 最近会话（含未闭合）:")
        if not recent_rows:
            lines.append("  - 无")
        else:
            for row in recent_rows[:5]:
                lines.append(
                    "  - "
                    f"#{row.get('id')} "
                    f"status={row.get('status') or '-'} "
                    f"sleep={row.get('sleep_time') or '-'} "
                    f"wake={row.get('wake_time') or '-'} "
                    f"duration={row.get('duration_minutes') if row.get('duration_minutes') is not None else '-'}m"
                )

        return "\n".join(lines)

    async def _call_llm(
        self,
        *,
        provider_id: str,
        system_prompt: str,
        prompt: str,
        scene: str,
    ) -> str | None:
        logger.debug(
            "[oyasumi] llm call start | scene=%s | provider=%s",
            scene,
            provider_id,
        )
        try:
            response = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    system_prompt=system_prompt,
                    prompt=prompt,
                    temperature=self.settings.llm_temperature,
                    max_tokens=self.settings.llm_max_tokens,
                ),
                timeout=self.settings.llm_timeout_sec,
            )
        except Exception as exc:
            logger.warning(
                "[oyasumi] llm call failed | scene=%s | error=%s", scene, exc
            )
            return None
        text = (getattr(response, "completion_text", "") or "").strip()
        logger.debug(
            "[oyasumi] llm call end | scene=%s | provider=%s | has_response=%s | response_chars=%s",
            scene,
            provider_id,
            bool(text),
            len(text or ""),
        )
        return text or None

    def _resolve_reply_provider_id(self, umo: str) -> str | None:
        return self._resolve_provider_id(umo, self.settings.llm_provider_id)

    def _resolve_analysis_provider_id(self, umo: str) -> str | None:
        return self._resolve_provider_id(
            umo,
            self.settings.llm_analysis_provider_id or self.settings.llm_provider_id,
        )

    def _resolve_provider_id(
        self,
        umo: str,
        configured_provider_id: str | None,
    ) -> str | None:
        if configured_provider_id:
            configured_provider = self.context.get_provider_by_id(
                configured_provider_id
            )
            if configured_provider is not None:
                return configured_provider_id
            logger.warning(
                "[oyasumi] configured provider not found: %s",
                configured_provider_id,
            )

        provider = self.context.get_using_provider(umo)
        if provider is None:
            providers = self.context.get_all_providers()
            provider = providers[0] if providers else None
        if provider is None:
            return None
        try:
            return str(provider.meta().id)
        except Exception:
            return None

    def _render_template(self, template: str, data: dict[str, Any]) -> str:
        return template.format_map(_SafeFormatDict(data))
