from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _csv_env(name: str) -> List[str]:
    raw_value = os.getenv(name, "")
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(
    name: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} doit etre un entier (actuel: {raw_value!r})") from exc

    if min_value is not None and value < min_value:
        raise ValueError(f"{name} doit etre >= {min_value} (actuel: {value})")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} doit etre <= {max_value} (actuel: {value})")
    return value


def _resolve_model_candidates(
    primary_env_name: str,
    fallback_env_name: str,
    default_primary: str,
    inherited_fallbacks: list[str] | None = None,
) -> list[str]:
    primary_model = os.getenv(primary_env_name, default_primary).strip()
    fallback_models = _csv_env(fallback_env_name)
    if not fallback_models:
        fallback_models = inherited_fallbacks or ["gpt-4.1-mini", "gpt-4o-mini"]

    model_candidates: list[str] = []
    for model in [primary_model, *fallback_models]:
        model = model.strip()
        if model and model not in model_candidates:
            model_candidates.append(model)
    return model_candidates


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    discord_webhook_url: str
    discord_suppress_embeds: bool
    token_usage_stats_path: str
    token_usage_report_in_discord: bool
    rss_feeds: List[str]
    model_name: str
    model_candidates: List[str]
    max_items_per_feed: int
    max_candidates: int
    shortlist_size: int
    timezone: str
    run_hour: int
    run_minute: int


@dataclass(frozen=True)
class CyberSettings:
    openai_api_key: str
    discord_webhook_url: str
    discord_suppress_embeds: bool
    discord_use_embeds: bool
    discord_include_item_embeds: bool
    discord_item_embeds_max: int
    suppress_initial_backlog: bool
    token_usage_stats_path: str
    token_usage_report_in_discord: bool
    rss_feeds: List[str]
    model_name: str
    model_candidates: List[str]
    max_items_per_feed: int
    max_new_items_per_run: int
    shortlist_size: int
    timezone: str
    run_minute: int
    seen_items_path: str


def load_settings() -> Settings:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    rss_feeds = _csv_env("RSS_FEEDS")

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY est manquant dans le .env")
    if not discord_webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL est manquant dans le .env")
    if not rss_feeds:
        raise ValueError("RSS_FEEDS est vide. Mets au moins un flux RSS.")

    model_candidates = _resolve_model_candidates(
        primary_env_name="OPENAI_MODEL",
        fallback_env_name="OPENAI_MODEL_FALLBACKS",
        default_primary="gpt-4.1-mini",
    )

    return Settings(
        openai_api_key=openai_api_key,
        discord_webhook_url=discord_webhook_url,
        discord_suppress_embeds=_bool_env("DISCORD_SUPPRESS_EMBEDS", True),
        token_usage_stats_path=os.getenv(
            "TOKEN_USAGE_STATS_PATH", "data/token_usage_stats.json"
        ).strip(),
        token_usage_report_in_discord=_bool_env(
            "TOKEN_USAGE_REPORT_IN_DISCORD", True
        ),
        rss_feeds=rss_feeds,
        model_name=model_candidates[0],
        model_candidates=model_candidates,
        max_items_per_feed=int(os.getenv("MAX_ITEMS_PER_FEED", "20")),
        max_candidates=int(os.getenv("MAX_CANDIDATES", "60")),
        shortlist_size=int(os.getenv("SHORTLIST_SIZE", "12")),
        timezone=os.getenv("TIMEZONE", "Europe/Paris").strip(),
        run_hour=_int_env("RUN_HOUR", 8, min_value=0, max_value=23),
        run_minute=_int_env("RUN_MINUTE", 30, min_value=0, max_value=59),
    )


def load_cyber_settings() -> CyberSettings:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    discord_webhook_url = os.getenv("CYBER_DISCORD_WEBHOOK_URL", "").strip()
    rss_feeds = _csv_env("CYBER_RSS_FEEDS")

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY est manquant dans le .env")
    if not discord_webhook_url:
        raise ValueError("CYBER_DISCORD_WEBHOOK_URL est manquant dans le .env")
    if not rss_feeds:
        raise ValueError("CYBER_RSS_FEEDS est vide. Mets au moins un flux RSS.")

    model_candidates = _resolve_model_candidates(
        primary_env_name="CYBER_OPENAI_MODEL",
        fallback_env_name="CYBER_OPENAI_MODEL_FALLBACKS",
        default_primary=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
        inherited_fallbacks=_csv_env("OPENAI_MODEL_FALLBACKS")
        or ["gpt-4.1-mini", "gpt-4o-mini"],
    )

    return CyberSettings(
        openai_api_key=openai_api_key,
        discord_webhook_url=discord_webhook_url,
        discord_suppress_embeds=_bool_env("CYBER_DISCORD_SUPPRESS_EMBEDS", True),
        discord_use_embeds=_bool_env("CYBER_DISCORD_USE_EMBEDS", True),
        discord_include_item_embeds=_bool_env(
            "CYBER_DISCORD_INCLUDE_ITEM_EMBEDS",
            False,
        ),
        discord_item_embeds_max=_int_env(
            "CYBER_DISCORD_ITEM_EMBEDS_MAX",
            3,
            min_value=0,
            max_value=25,
        ),
        suppress_initial_backlog=_bool_env("CYBER_SUPPRESS_INITIAL_BACKLOG", False),
        token_usage_stats_path=os.getenv(
            "CYBER_TOKEN_USAGE_STATS_PATH",
            "data/cyber_token_usage_stats.json",
        ).strip(),
        token_usage_report_in_discord=_bool_env(
            "CYBER_TOKEN_USAGE_REPORT_IN_DISCORD",
            True,
        ),
        rss_feeds=rss_feeds,
        model_name=model_candidates[0],
        model_candidates=model_candidates,
        max_items_per_feed=int(os.getenv("CYBER_MAX_ITEMS_PER_FEED", "30")),
        max_new_items_per_run=int(os.getenv("CYBER_MAX_NEW_ITEMS_PER_RUN", "30")),
        shortlist_size=int(os.getenv("CYBER_SHORTLIST_SIZE", "12")),
        timezone=os.getenv("TIMEZONE", "Europe/Paris").strip(),
        run_minute=_int_env("CYBER_RUN_MINUTE", 0, min_value=0, max_value=59),
        seen_items_path=os.getenv(
            "CYBER_SEEN_ITEMS_PATH",
            "data/cyber_seen_items.json",
        ).strip(),
    )