from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

LOGGER = logging.getLogger(__name__)


class CyberSeenStore:
    def __init__(self, path: str, max_seen: int = 10000):
        self.path = Path(path)
        self.max_seen = max_seen

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_payload(self) -> dict:
        now = self._now_iso()
        return {
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
            "seen_entry_ids": [],
        }

    def _load_payload(self) -> dict:
        if not self.path.exists():
            return self._default_payload()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("seen_entry_ids", [])
                return data
        except Exception:
            LOGGER.exception("Impossible de lire l'etat cyber vu: %s", self.path)
        return self._default_payload()

    def _save_payload(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def is_initialized(self) -> bool:
        return self.path.exists()

    def load_seen_ids(self) -> set[str]:
        payload = self._load_payload()
        seen_raw = payload.get("seen_entry_ids", [])
        if not isinstance(seen_raw, list):
            return set()
        return {str(value) for value in seen_raw if str(value).strip()}

    def mark_seen(self, entry_ids: Iterable[str]) -> None:
        new_ids = [entry_id for entry_id in entry_ids if entry_id]
        if not new_ids:
            return

        payload = self._load_payload()
        current = payload.get("seen_entry_ids", [])
        if not isinstance(current, list):
            current = []

        merged: list[str] = []
        seen: set[str] = set()
        for entry_id in [*new_ids, *current]:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            merged.append(entry_id)

        payload["seen_entry_ids"] = merged[: self.max_seen]
        payload["updated_at"] = self._now_iso()
        payload.setdefault("created_at", self._now_iso())

        self._save_payload(payload)