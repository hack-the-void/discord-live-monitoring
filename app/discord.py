from __future__ import annotations

import logging
from typing import Any, List

import requests

LOGGER = logging.getLogger(__name__)

_DISCORD_MAX = 1900
_MAX_EMBEDS_PER_REQUEST = 10
_MAX_EMBED_CHARS_PER_REQUEST = 5500
_MAX_EMBED_FIELDS = 25
_MAX_EMBED_TITLE = 256
_MAX_EMBED_DESCRIPTION = 4096
_MAX_EMBED_FIELD_NAME = 256
_MAX_EMBED_FIELD_VALUE = 1024
_MAX_EMBED_FOOTER = 2048
_MAX_EMBED_AUTHOR = 256


def _chunk_message(text: str, max_len: int = _DISCORD_MAX) -> List[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if line_len > max_len:
            if current:
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
            start = 0
            while start < len(line):
                chunks.append(line[start : start + max_len])
                start += max_len
            continue

        if current_len + line_len > max_len:
            chunks.append("\n".join(current).strip())
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def send_discord_message(
    webhook_url: str, content: str, suppress_embeds: bool = True
) -> None:
    for chunk in _chunk_message(content):
        payload = {
            "content": chunk,
            "allowed_mentions": {"parse": []},
        }
        if suppress_embeds:
            payload["flags"] = 4

        response = requests.post(webhook_url, json=payload, timeout=30)
        if response.status_code not in (200, 204):
            raise RuntimeError(
                "Erreur envoi Discord: "
                f"status={response.status_code}, body={response.text[:300]}"
            )
    LOGGER.info("Digest envoyé sur Discord")


def send_discord_embeds(
    webhook_url: str,
    embeds: list[dict[str, Any]],
    content: str = "",
) -> None:
    if not embeds and not content.strip():
        return

    safe_content = content.strip()[:_DISCORD_MAX]
    sanitized = [_sanitize_embed(embed) for embed in embeds]
    chunks = _chunk_embeds(sanitized) or [[]]

    for idx, chunk in enumerate(chunks):
        payload: dict[str, Any] = {
            "allowed_mentions": {"parse": []},
        }
        if idx == 0 and safe_content:
            payload["content"] = safe_content
        if chunk:
            payload["embeds"] = chunk

        response = requests.post(webhook_url, json=payload, timeout=30)
        if response.status_code not in (200, 204):
            raise RuntimeError(
                "Erreur envoi Discord embeds: "
                f"status={response.status_code}, body={response.text[:300]}"
            )
    LOGGER.info("Embeds envoyés sur Discord")


def _truncate_text(value: str, max_len: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1].rstrip() + "…"


def _sanitize_embed(embed: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(embed)

    if "title" in sanitized:
        sanitized["title"] = _truncate_text(str(sanitized.get("title", "")), _MAX_EMBED_TITLE)
    if "description" in sanitized:
        sanitized["description"] = _truncate_text(
            str(sanitized.get("description", "")),
            _MAX_EMBED_DESCRIPTION,
        )

    fields = sanitized.get("fields")
    if isinstance(fields, list):
        clean_fields: list[dict[str, Any]] = []
        for field in fields[:_MAX_EMBED_FIELDS]:
            if not isinstance(field, dict):
                continue
            clean_fields.append(
                {
                    "name": _truncate_text(str(field.get("name", "")), _MAX_EMBED_FIELD_NAME) or "-",
                    "value": _truncate_text(str(field.get("value", "")), _MAX_EMBED_FIELD_VALUE)
                    or "-",
                    "inline": bool(field.get("inline", False)),
                }
            )
        sanitized["fields"] = clean_fields

    footer = sanitized.get("footer")
    if isinstance(footer, dict):
        footer_text = _truncate_text(str(footer.get("text", "")), _MAX_EMBED_FOOTER)
        sanitized["footer"] = {"text": footer_text} if footer_text else {}

    author = sanitized.get("author")
    if isinstance(author, dict):
        author_name = _truncate_text(str(author.get("name", "")), _MAX_EMBED_AUTHOR)
        if author_name:
            sanitized["author"] = {"name": author_name}
        else:
            sanitized.pop("author", None)

    return sanitized


def _embed_char_count(embed: dict[str, Any]) -> int:
    total = 0
    total += len(str(embed.get("title", "")))
    total += len(str(embed.get("description", "")))

    footer = embed.get("footer")
    if isinstance(footer, dict):
        total += len(str(footer.get("text", "")))

    author = embed.get("author")
    if isinstance(author, dict):
        total += len(str(author.get("name", "")))

    fields = embed.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            total += len(str(field.get("name", "")))
            total += len(str(field.get("value", "")))

    return total


def _chunk_embeds(embeds: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = []
    current_chars = 0

    for embed in embeds:
        embed_size = _embed_char_count(embed)
        if current_chunk and (
            len(current_chunk) >= _MAX_EMBEDS_PER_REQUEST
            or current_chars + embed_size > _MAX_EMBED_CHARS_PER_REQUEST
        ):
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0

        current_chunk.append(embed)
        current_chars += embed_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks