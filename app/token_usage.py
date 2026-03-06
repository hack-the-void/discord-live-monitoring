from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "llm_calls")


def empty_usage() -> dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
    }


def normalize_usage(raw_usage: Any) -> dict[str, int]:
    if not isinstance(raw_usage, dict):
        return empty_usage()

    prompt_tokens = int(raw_usage.get("input_tokens", raw_usage.get("prompt_tokens", 0)) or 0)
    completion_tokens = int(
        raw_usage.get("output_tokens", raw_usage.get("completion_tokens", 0)) or 0
    )
    total_tokens = int(raw_usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "llm_calls": int(raw_usage.get("llm_calls", 0) or 0),
    }


def merge_usage(target: dict[str, int], source: dict[str, int]) -> dict[str, int]:
    for key in _USAGE_KEYS:
        target[key] = int(target.get(key, 0)) + int(source.get(key, 0))
    return target


def extract_usage_from_response(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    parsed = normalize_usage(usage)
    if parsed["total_tokens"] > 0:
        return parsed

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        parsed = normalize_usage(response_metadata.get("token_usage") or response_metadata.get("usage"))
        if parsed["total_tokens"] > 0:
            return parsed

    return empty_usage()


class TokenUsageStore:
    def __init__(self, path: str):
        self.path = Path(path)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_payload(self) -> dict[str, Any]:
        now = self._now_iso()
        return {
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
            "totals": {
                "runs": 0,
                **empty_usage(),
            },
            "by_model": {},
            "last_run": {},
        }

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_payload()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            LOGGER.exception("Impossible de lire le fichier de stats tokens: %s", self.path)
        return self._default_payload()

    def _save_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def record_run(
        self,
        run_usage: dict[str, int],
        by_model: dict[str, dict[str, int]],
    ) -> dict[str, Any]:
        payload = self._load_payload()
        totals = payload.setdefault("totals", {"runs": 0, **empty_usage()})
        totals["runs"] = int(totals.get("runs", 0)) + 1
        merge_usage(totals, normalize_usage(run_usage))

        model_totals = payload.setdefault("by_model", {})
        for model_name, usage in by_model.items():
            current = model_totals.setdefault(
                model_name,
                {"runs": 0, **empty_usage()},
            )
            current["runs"] = int(current.get("runs", 0)) + 1
            merge_usage(current, normalize_usage(usage))

        now = self._now_iso()
        payload["updated_at"] = now
        payload["last_run"] = {
            "at": now,
            "usage": normalize_usage(run_usage),
            "by_model": {model: normalize_usage(usage) for model, usage in by_model.items()},
        }

        self._save_payload(payload)
        return {
            "path": str(self.path),
            "run": normalize_usage(run_usage),
            "totals": {
                "runs": int(totals.get("runs", 0)),
                **normalize_usage(totals),
            },
        }