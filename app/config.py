from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger

DEFAULT_MORNING_PATTERNS = [r"^(早安|早上好|我醒了).*$"]
DEFAULT_NIGHT_PATTERNS = [r"^(晚安|睡觉了|我要睡了).*$"]
VALID_REPLY_MODES = {"static", "llm"}
VALID_DUPLICATE_POLICIES = {"ignore", "update_open", "create_new"}
VALID_ORPHAN_POLICIES = {"warn_only", "create_closed_session"}


@dataclass(frozen=True)
class PluginSettings:
    enabled: bool
    reply_mode: str
    good_morning_patterns: list[str]
    good_night_patterns: list[str]
    ignore_case: bool
    normalize_width: bool
    morning_static_reply: str
    night_static_reply: str
    orphan_morning_reply: str
    duplicate_night_reply: str
    llm_enabled: bool
    llm_provider_id: str | None
    llm_fallback_to_static: bool
    llm_temperature: float
    llm_max_tokens: int
    llm_timeout_sec: int
    llm_prompt_morning: str
    llm_prompt_night: str
    llm_prompt_analysis: str
    day_boundary_hour: int
    duplicate_night_policy: str
    orphan_morning_policy: str
    auto_fill_default_hours: int
    allow_user_edit_self: bool
    admin_only_global_query: bool
    max_open_session_hours: int
    include_auto_fill_in_stats: bool
    standalone_webui_enabled: bool
    standalone_webui_host: str
    standalone_webui_port: int
    standalone_webui_token: str
    plugin_data_dir: Path
    db_path: Path
    sql_init_path: Path
    snapshot_path: Path


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _parse_pattern_text(value: Any, fallback: list[str]) -> list[str]:
    text = _as_str(value, "").strip()
    if not text:
        return fallback
    patterns: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        candidate = line.strip()
        if not candidate:
            continue
        patterns.append(candidate)
    return patterns or fallback


def load_plugin_settings(
    raw_config: dict[str, Any] | None,
    plugin_name: str,
    plugin_data_dir: Path,
    sql_init_path: Path,
) -> PluginSettings:
    raw = raw_config or {}
    plugin_data_dir = Path(plugin_data_dir)
    plugin_data_dir.mkdir(parents=True, exist_ok=True)

    reply_mode = _as_str(raw.get("reply_mode"), "static").strip().lower()
    if reply_mode not in VALID_REPLY_MODES:
        logger.warning(
            "[%s] invalid reply_mode=%s, fallback to static",
            plugin_name,
            reply_mode,
        )
        reply_mode = "static"

    duplicate_night_policy = _as_str(
        raw.get("duplicate_night_policy"), "ignore"
    ).strip()
    if duplicate_night_policy not in VALID_DUPLICATE_POLICIES:
        logger.warning(
            "[%s] invalid duplicate_night_policy=%s, fallback to ignore",
            plugin_name,
            duplicate_night_policy,
        )
        duplicate_night_policy = "ignore"

    orphan_morning_policy = _as_str(
        raw.get("orphan_morning_policy"), "warn_only"
    ).strip()
    if orphan_morning_policy not in VALID_ORPHAN_POLICIES:
        logger.warning(
            "[%s] invalid orphan_morning_policy=%s, fallback to warn_only",
            plugin_name,
            orphan_morning_policy,
        )
        orphan_morning_policy = "warn_only"

    day_boundary_hour = _as_int(raw.get("day_boundary_hour"), 6)
    day_boundary_hour = max(0, min(day_boundary_hour, 12))

    llm_provider_id = _as_str(raw.get("llm_provider_id"), "").strip() or None
    standalone_webui_host = (
        _as_str(raw.get("standalone_webui_host"), "127.0.0.1").strip() or "127.0.0.1"
    )
    standalone_webui_port = max(
        1,
        min(_as_int(raw.get("standalone_webui_port"), 6196), 65535),
    )

    return PluginSettings(
        enabled=_as_bool(raw.get("enabled"), True),
        reply_mode=reply_mode,
        good_morning_patterns=_parse_pattern_text(
            raw.get("good_morning_patterns_text"),
            DEFAULT_MORNING_PATTERNS,
        ),
        good_night_patterns=_parse_pattern_text(
            raw.get("good_night_patterns_text"),
            DEFAULT_NIGHT_PATTERNS,
        ),
        ignore_case=_as_bool(raw.get("ignore_case"), True),
        normalize_width=_as_bool(raw.get("normalize_width"), True),
        morning_static_reply=_as_str(
            raw.get("morning_static_reply"),
            "早安呀，{user_name}。你这次睡了约 {duration_minutes} 分钟，要元气满满哦，喵~",
        ),
        night_static_reply=_as_str(
            raw.get("night_static_reply"),
            "晚安啦，{user_name}。已经帮你记下入睡时间 {sleep_time}，做个好梦喵~",
        ),
        orphan_morning_reply=_as_str(
            raw.get("orphan_morning_reply"),
            "收到早安啦，但还没找到可闭合的晚安记录。可以用“/作息 修正”补录一下，喵~",
        ),
        duplicate_night_reply=_as_str(
            raw.get("duplicate_night_reply"),
            "你当前已经有进行中的睡眠记录了，这次按策略处理好啦，喵~",
        ),
        llm_enabled=_as_bool(raw.get("llm_enabled"), False),
        llm_provider_id=llm_provider_id,
        llm_fallback_to_static=_as_bool(raw.get("llm_fallback_to_static"), True),
        llm_temperature=max(0.0, min(_as_float(raw.get("llm_temperature"), 0.4), 1.5)),
        llm_max_tokens=max(64, _as_int(raw.get("llm_max_tokens"), 300)),
        llm_timeout_sec=max(5, _as_int(raw.get("llm_timeout_sec"), 20)),
        llm_prompt_morning=_as_str(
            raw.get("llm_prompt_morning"),
            "你是温柔可爱的作息助手。请基于早安记录回复1-2句，50字内，不分点不换行；给出问候+1条轻建议，可带一次“喵~”。",
        ),
        llm_prompt_night=_as_str(
            raw.get("llm_prompt_night"),
            "你是温柔可爱的作息助手。请基于晚安记录回复1-2句，50字内，不分点不换行；给出晚安+1条轻建议，可带一次“喵~”。",
        ),
        llm_prompt_analysis=_as_str(
            raw.get("llm_prompt_analysis"),
            "你是二次元群聊里的作息观察员。请严格遵循当前会话人格（persona）来表达，再基于睡眠统计输出 Markdown，包含「## 作息播报」「## 规律雷达」「## 明日行动清单」三个部分，语气轻松友好、带少量 ACG 风格，不油腻；给出3条可执行建议。",
        ),
        day_boundary_hour=day_boundary_hour,
        duplicate_night_policy=duplicate_night_policy,
        orphan_morning_policy=orphan_morning_policy,
        auto_fill_default_hours=max(1, _as_int(raw.get("auto_fill_default_hours"), 8)),
        allow_user_edit_self=_as_bool(raw.get("allow_user_edit_self"), True),
        admin_only_global_query=_as_bool(raw.get("admin_only_global_query"), True),
        max_open_session_hours=max(1, _as_int(raw.get("max_open_session_hours"), 20)),
        include_auto_fill_in_stats=_as_bool(
            raw.get("include_auto_fill_in_stats"), True
        ),
        standalone_webui_enabled=_as_bool(
            raw.get("standalone_webui_enabled"),
            True,
        ),
        standalone_webui_host=standalone_webui_host,
        standalone_webui_port=standalone_webui_port,
        standalone_webui_token=_as_str(raw.get("standalone_webui_token"), "").strip(),
        plugin_data_dir=plugin_data_dir,
        db_path=plugin_data_dir / "oyasumi.db",
        sql_init_path=Path(sql_init_path),
        snapshot_path=plugin_data_dir / "webui_snapshot.json",
    )
