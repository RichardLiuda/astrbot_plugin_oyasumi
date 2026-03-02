from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger


class SnapshotService:
    def __init__(self, snapshot_path: Path):
        self.snapshot_path = Path(snapshot_path)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, payload: dict[str, Any]) -> None:
        temp_path = self.snapshot_path.with_suffix(".tmp")
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(self.snapshot_path)

    def build_event_snapshot(
        self,
        *,
        user_id: str,
        dashboard: dict[str, Any],
        last_action: str,
    ) -> dict[str, Any]:
        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user_id,
            "last_action": last_action,
            "dashboard": dashboard,
        }

    def safe_write(self, payload: dict[str, Any]) -> None:
        try:
            self.write_snapshot(payload)
        except Exception as exc:
            logger.warning("[oyasumi] failed to write snapshot: %s", exc)
