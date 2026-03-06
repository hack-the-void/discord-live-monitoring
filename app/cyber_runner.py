from __future__ import annotations

import logging
from typing import Any

from .config import CyberSettings, load_cyber_settings
from .cyber_graph import build_cyber_watch_graph

LOGGER = logging.getLogger(__name__)


def run_cyber_watch_once(settings: CyberSettings | None = None) -> dict[str, Any]:
    settings = settings or load_cyber_settings()
    app = build_cyber_watch_graph(settings)

    initial_state = {
        "feed_items": [],
        "new_items": [],
        "new_entry_ids": [],
        "shortlisted_items": [],
        "digest_markdown": "",
        "token_usage_summary": {},
        "sent": False,
        "errors": [],
    }

    result = app.invoke(initial_state)
    new_count = len(result.get("new_entry_ids", []))
    sent = bool(result.get("sent", False))
    LOGGER.info("Execution cyber terminee | nouveaux=%s | envoye=%s", new_count, sent)
    return result