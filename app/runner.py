from __future__ import annotations

import logging

from .config import Settings, load_settings
from .graph import build_watch_graph

LOGGER = logging.getLogger(__name__)


def run_watch_once(settings: Settings | None = None) -> str:
    settings = settings or load_settings()
    app = build_watch_graph(settings)

    initial_state = {
        "feed_items": [],
        "shortlisted_items": [],
        "digest_markdown": "",
        "token_usage_summary": {},
        "errors": [],
    }

    result = app.invoke(initial_state)
    digest = result.get("digest_markdown", "")
    LOGGER.info("Exécution terminée")
    return digest