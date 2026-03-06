from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from typing import List

import feedparser

from .config import CyberSettings
from .models import CyberFeedItem

LOGGER = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)


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


def _entry_id(
    source_title: str,
    title: str,
    link: str,
    published_at: str,
    entry: feedparser.FeedParserDict,
) -> str:
    raw = (
        str(entry.get("id") or "").strip()
        or str(entry.get("guid") or "").strip()
        or link
        or f"{source_title}|{title}|{published_at}"
    )
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _extract_cve_ids(title: str, summary: str) -> list[str]:
    found = _CVE_RE.findall(f"{title}\n{summary}")
    deduped: list[str] = []
    seen: set[str] = set()
    for cve_id in found:
        normalized = cve_id.upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def collect_cyber_feed_items(settings: CyberSettings) -> List[CyberFeedItem]:
    items: list[CyberFeedItem] = []
    seen_ids: set[str] = set()

    for url in settings.rss_feeds:
        feed = feedparser.parse(url)
        source_title = _clean_text(feed.feed.get("title", url), max_len=140)

        if feed.bozo:
            LOGGER.warning("Flux potentiellement invalide: %s", url)

        for entry in feed.entries[: settings.max_items_per_feed]:
            title = _clean_text(entry.get("title", "Sans titre"), max_len=260)
            link = (entry.get("link") or "").strip()
            summary = _clean_text(
                entry.get("summary") or entry.get("description") or "",
                max_len=900,
            )
            published_at = _published_iso(entry)
            entry_id = _entry_id(source_title, title, link, published_at, entry)

            if not entry_id or entry_id in seen_ids:
                continue

            cve_ids = _extract_cve_ids(title, summary)

            items.append(
                CyberFeedItem(
                    entry_id=entry_id,
                    title=title,
                    link=link,
                    summary=summary,
                    published_at=published_at,
                    source=source_title,
                    cve_ids=cve_ids,
                )
            )
            seen_ids.add(entry_id)

    items.sort(key=lambda item: item.published_at, reverse=True)
    LOGGER.info("%s items cyber RSS collectés", len(items))
    return items