from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from astrbot.api import logger

from .config import PluginSettings

EVENT_GOOD_MORNING = "good_morning"
EVENT_GOOD_NIGHT = "good_night"
MAX_PATTERN_LENGTH = 128
MAX_QUANTIFIER_COUNT = 12
MAX_MATCH_TEXT_LENGTH = 256


@dataclass(frozen=True)
class TriggerMatchResult:
    event_type: str
    matched_pattern: str
    normalized_text: str


class TriggerMatcher:
    def __init__(self, settings: PluginSettings):
        self._settings = settings
        self._morning_patterns: list[tuple[str, re.Pattern[str]]] = []
        self._night_patterns: list[tuple[str, re.Pattern[str]]] = []
        self.reload(settings)

    def reload(self, settings: PluginSettings) -> None:
        self._settings = settings
        flags = re.IGNORECASE if settings.ignore_case else 0
        self._morning_patterns = self._compile_patterns(
            settings.good_morning_patterns, flags, "good_morning"
        )
        self._night_patterns = self._compile_patterns(
            settings.good_night_patterns, flags, "good_night"
        )

    def normalize_text(self, text: str) -> str:
        normalized = text.strip()
        if self._settings.normalize_width:
            normalized = unicodedata.normalize("NFKC", normalized)
        return normalized

    def match(self, text: str) -> TriggerMatchResult | None:
        normalized = self.normalize_text(text)
        if not normalized:
            return None
        if len(normalized) > MAX_MATCH_TEXT_LENGTH:
            normalized = normalized[:MAX_MATCH_TEXT_LENGTH]

        for pattern_text, pattern in self._night_patterns:
            if pattern.search(normalized):
                return TriggerMatchResult(
                    event_type=EVENT_GOOD_NIGHT,
                    matched_pattern=pattern_text,
                    normalized_text=normalized,
                )

        for pattern_text, pattern in self._morning_patterns:
            if pattern.search(normalized):
                return TriggerMatchResult(
                    event_type=EVENT_GOOD_MORNING,
                    matched_pattern=pattern_text,
                    normalized_text=normalized,
                )
        return None

    def _compile_patterns(
        self,
        patterns: list[str],
        flags: int,
        pattern_group_name: str,
    ) -> list[tuple[str, re.Pattern[str]]]:
        compiled: list[tuple[str, re.Pattern[str]]] = []
        for pattern_text in patterns:
            if not self._is_pattern_safe(pattern_text):
                logger.warning(
                    "[oyasumi] unsafe %s pattern skipped: %s",
                    pattern_group_name,
                    pattern_text,
                )
                continue
            try:
                compiled.append((pattern_text, re.compile(pattern_text, flags)))
            except re.error as exc:
                logger.warning(
                    "[oyasumi] invalid %s pattern skipped: %s (%s)",
                    pattern_group_name,
                    pattern_text,
                    exc,
                )
        return compiled

    def _is_pattern_safe(self, pattern_text: str) -> bool:
        if not pattern_text or len(pattern_text) > MAX_PATTERN_LENGTH:
            return False

        quantifier_count = len(re.findall(r"[*+?]|\{\d+(?:,\d*)?\}", pattern_text))
        if quantifier_count > MAX_QUANTIFIER_COUNT:
            return False

        # Heuristic guards for catastrophic backtracking hotspots.
        if re.search(r"\([^)]*[*+][^)]*\)[*+]", pattern_text):
            return False
        if re.search(r"\.\*.*\.\*", pattern_text):
            return False
        if re.search(r"\\[1-9]", pattern_text):
            return False

        return True
