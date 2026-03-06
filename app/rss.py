from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import List

import feedparser

from .config import Settings
from .models import FeedItem

LOGGER = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: str, max_len: int = 500) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _published_iso(entry: feedparser.FeedParserDict) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return ""
    try:
        dt = datetime(*parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


def collect_feed_items(settings: Settings) -> List[FeedItem]:
    items: list[FeedItem] = []
    seen_links: set[str] = set()

    for url in settings.rss_feeds:
        feed = feedparser.parse(url)
        source_title = _clean_text(feed.feed.get("title", url), max_len=120)

        if feed.bozo:
            LOGGER.warning("Flux potentiellement invalide: %s", url)

        for entry in feed.entries[: settings.max_items_per_feed]:
            link = (entry.get("link") or "").strip()
            if not link or link in seen_links:
                continue

            title = _clean_text(entry.get("title", "Sans titre"), max_len=220)
            summary = _clean_text(
                entry.get("summary") or entry.get("description") or "",
                max_len=700,
            )
            published_at = _published_iso(entry)

            items.append(
                FeedItem(
                    title=title,
                    link=link,
                    summary=summary,
                    published_at=published_at,
                    source=source_title,
                )
            )
            seen_links.add(link)

    items.sort(key=lambda item: item.published_at, reverse=True)
    LOGGER.info("%s items RSS collectés", len(items))
    return items