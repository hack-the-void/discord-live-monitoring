from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from .config import CyberSettings
from .cyber_rss import collect_cyber_feed_items
from .cyber_seen_store import CyberSeenStore
from .discord import send_discord_embeds, send_discord_message
from .models import ShortlistOutput
from .token_usage import (
    TokenUsageStore,
    empty_usage,
    extract_usage_from_response,
    merge_usage,
)

LOGGER = logging.getLogger(__name__)


def _truncate(text: str, max_len: int) -> str:
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return value[:max_len]
    return value[: max_len - 1].rstrip() + "…"


def _build_cyber_embeds(
    digest: str,
    shortlisted_items: list[dict[str, Any]],
    new_count: int,
    token_usage_summary: dict[str, Any],
    errors: list[str],
    include_item_embeds: bool,
    item_embeds_max: int,
) -> list[dict[str, Any]]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    clean_digest = (digest or "").replace("|", " ").strip()

    summary_embed: dict[str, Any] = {
        "title": f"Veille Cyber CVE - {now}",
        "description": _truncate(
            clean_digest or "Nouvelles alertes CVE détectées.",
            3800,
        ),
        "color": 0xCC0000,
        "fields": [
            {"name": "Nouveautés", "value": str(new_count), "inline": True},
            {"name": "Alertes retenues", "value": str(len(shortlisted_items)), "inline": True},
        ],
    }

    if token_usage_summary:
        run_stats = token_usage_summary.get("run", {})
        total_stats = token_usage_summary.get("totals", {})
        summary_embed["fields"].append(
            {
                "name": "Tokens (run)",
                "value": (
                    f"prompt={run_stats.get('prompt_tokens', 0)} | "
                    f"completion={run_stats.get('completion_tokens', 0)} | "
                    f"total={run_stats.get('total_tokens', 0)}"
                ),
                "inline": False,
            }
        )
        summary_embed["fields"].append(
            {
                "name": "Tokens (cumul)",
                "value": (
                    f"total={total_stats.get('total_tokens', 0)} | "
                    f"runs={total_stats.get('runs', 0)} | "
                    f"calls={total_stats.get('llm_calls', 0)}"
                ),
                "inline": False,
            }
        )

    if errors:
        summary_embed["fields"].append(
            {
                "name": "Logs techniques",
                "value": _truncate("\n".join(f"- {err}" for err in errors), 1000),
                "inline": False,
            }
        )

    embeds: list[dict[str, Any]] = [summary_embed]

    if not include_item_embeds or item_embeds_max <= 0:
        return embeds

    for item in shortlisted_items[:item_embeds_max]:
        cve_ids = item.get("cve_ids", [])
        cve_text = ", ".join(cve_ids) if cve_ids else "N/A"
        title = item.get("title", "Alerte CVE")
        link = item.get("link", "")
        summary = item.get("summary", "")
        source = item.get("source", "N/A")
        published = item.get("published_at", "N/A")

        vuln_embed: dict[str, Any] = {
            "title": _truncate(title, 250),
            "description": _truncate(summary or "Aucun résumé disponible.", 700),
            "color": 0xE67E22,
            "fields": [
                {"name": "CVE", "value": _truncate(cve_text, 1000), "inline": False},
                {"name": "Source", "value": _truncate(source, 1000), "inline": True},
                {"name": "Date", "value": _truncate(published, 1000), "inline": True},
            ],
        }
        if link:
            vuln_embed["url"] = link
            vuln_embed["fields"].append(
                {"name": "Lien", "value": f"[Voir le détail]({link})", "inline": False}
            )

        embeds.append(vuln_embed)

    return embeds


class CyberWatchState(TypedDict):
    feed_items: list[dict[str, Any]]
    new_items: list[dict[str, Any]]
    new_entry_ids: list[str]
    shortlisted_items: list[dict[str, Any]]
    digest_markdown: str
    token_usage_summary: dict[str, Any]
    sent: bool
    errors: list[str]


def build_cyber_watch_graph(settings: CyberSettings):
    active_model = settings.model_name
    run_usage = empty_usage()
    usage_by_model: dict[str, dict[str, int]] = {}
    seen_store = CyberSeenStore(settings.seen_items_path)

    def _build_llm(model: str) -> ChatOpenAI:
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=model,
            temperature=0.1,
        )

    def _looks_like_model_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "model_not_found" in text
            or "does not exist" in text
            or "do not have access" in text
            or "invalid model" in text
            or "unknown model" in text
        )

    def _invoke_with_model_fallback(messages, structured: bool = False):
        nonlocal active_model
        ordered_models = [active_model] + [
            model for model in settings.model_candidates if model != active_model
        ]

        last_model_exc: Exception | None = None
        for model in ordered_models:
            llm = _build_llm(model)
            try:
                if structured:
                    structured_result = llm.with_structured_output(
                        ShortlistOutput,
                        include_raw=True,
                    ).invoke(messages)
                    parsed = structured_result.get("parsed")
                    raw = structured_result.get("raw")
                    if parsed is None:
                        raise RuntimeError(
                            "Réponse structurée invalide: "
                            f"{structured_result.get('parsing_error')}"
                        )
                    usage = extract_usage_from_response(raw)
                    if usage["total_tokens"] > 0:
                        usage["llm_calls"] = 1
                        merge_usage(run_usage, usage)
                        merge_usage(
                            usage_by_model.setdefault(model, empty_usage()),
                            usage,
                        )
                    result = parsed
                else:
                    result = llm.invoke(messages)
                    usage = extract_usage_from_response(result)
                    if usage["total_tokens"] > 0:
                        usage["llm_calls"] = 1
                        merge_usage(run_usage, usage)
                        merge_usage(
                            usage_by_model.setdefault(model, empty_usage()),
                            usage,
                        )

                if model != active_model:
                    LOGGER.warning(
                        "Bascule modèle OpenAI (cyber): %s -> %s",
                        active_model,
                        model,
                    )
                active_model = model
                return result
            except Exception as exc:
                if _looks_like_model_error(exc):
                    last_model_exc = exc
                    LOGGER.warning("Modèle indisponible (cyber): %s (%s)", model, exc)
                    continue
                raise

        raise RuntimeError(
            "Aucun modèle OpenAI accessible (cyber) parmi: "
            f"{', '.join(ordered_models)}. Dernière erreur: {last_model_exc}"
        )

    def fetch_node(_: CyberWatchState) -> CyberWatchState:
        try:
            items = collect_cyber_feed_items(settings)
            seen_ids = seen_store.load_seen_ids()
            if (
                settings.suppress_initial_backlog
                and not seen_ids
                and items
                and not seen_store.is_initialized()
            ):
                baseline_ids = [item.entry_id for item in items]
                seen_store.mark_seen(baseline_ids)
                LOGGER.info(
                    (
                        "Initialisation cyber: %s items marques comme deja vus. "
                        "Aucun envoi Discord sur ce premier passage."
                    ),
                    len(baseline_ids),
                )
                return {
                    "feed_items": [item.model_dump() for item in items],
                    "new_items": [],
                    "new_entry_ids": [],
                    "shortlisted_items": [],
                    "digest_markdown": "",
                    "token_usage_summary": {},
                    "sent": False,
                    "errors": [],
                }

            new_items = [item for item in items if item.entry_id not in seen_ids]
            if settings.max_new_items_per_run > 0:
                new_items = new_items[: settings.max_new_items_per_run]

            return {
                "feed_items": [item.model_dump() for item in items],
                "new_items": [item.model_dump() for item in new_items],
                "new_entry_ids": [item.entry_id for item in new_items],
                "shortlisted_items": [],
                "digest_markdown": "",
                "token_usage_summary": {},
                "sent": False,
                "errors": [],
            }
        except Exception as exc:
            LOGGER.exception("Erreur récupération RSS cyber")
            return {
                "feed_items": [],
                "new_items": [],
                "new_entry_ids": [],
                "shortlisted_items": [],
                "digest_markdown": "",
                "token_usage_summary": {},
                "sent": False,
                "errors": [f"Erreur RSS cyber: {exc}"],
            }

    def shortlist_node(state: CyberWatchState) -> CyberWatchState:
        new_items = state.get("new_items", [])
        if not new_items:
            return {**state, "shortlisted_items": []}

        prompt_lines = []
        for idx, item in enumerate(new_items):
            cve_ids = item.get("cve_ids", [])
            cve_text = ", ".join(cve_ids) if cve_ids else "N/A"
            prompt_lines.append(
                (
                    f"[{idx}] {item.get('title', '')}\n"
                    f"CVE: {cve_text}\n"
                    f"Source: {item.get('source', '')}\n"
                    f"Date: {item.get('published_at', '')}\n"
                    f"Résumé: {item.get('summary', '')}\n"
                    f"Lien: {item.get('link', '')}"
                )
            )

        messages = [
            SystemMessage(
                content=(
                    "Tu es un analyste SOC orienté gestion de vulnérabilités. "
                    "Sélectionne les alertes CVE avec impact opérationnel élevé: "
                    "exploitation active, gravité critique, surface d'attaque large, "
                    "technos très utilisées. Évite les doublons. "
                    "Sois strict: ne sélectionne rien si aucune alerte n'est réellement "
                    "prioritaire."
                )
            ),
            HumanMessage(
                content=(
                    (
                        f"Choisis jusqu'à {settings.shortlist_size} indices d'alertes "
                        "prioritaires, triés par importance décroissante. "
                        "Tu peux retourner une liste vide si aucune alerte n'est "
                        "suffisamment critique.\n\n"
                    )
                    + "\n\n".join(prompt_lines)
                )
            ),
        ]

        try:
            result = _invoke_with_model_fallback(messages, structured=True)
            picked: list[int] = []
            seen = set()
            for idx in result.selected_indices:
                if idx in seen:
                    continue
                if 0 <= idx < len(new_items):
                    seen.add(idx)
                    picked.append(idx)

            if not picked:
                LOGGER.info(
                    "Shortlist cyber: aucune alerte assez critique parmi %s nouveautes",
                    len(new_items),
                )
                return {**state, "shortlisted_items": []}

            shortlisted = [new_items[idx] for idx in picked[: settings.shortlist_size]]
            return {**state, "shortlisted_items": shortlisted}
        except Exception as exc:
            LOGGER.exception("Erreur shortlist cyber")
            fallback = new_items[: settings.shortlist_size]
            return {
                **state,
                "shortlisted_items": fallback,
                "errors": [*state.get("errors", []), f"Shortlist cyber fallback: {exc}"],
            }

    def digest_node(state: CyberWatchState) -> CyberWatchState:
        shortlisted = state.get("shortlisted_items", [])
        if not shortlisted:
            return {
                **state,
                "digest_markdown": "",
            }

        digest_input = []
        for item in shortlisted:
            cve_ids = item.get("cve_ids", [])
            cve_text = ", ".join(cve_ids) if cve_ids else "N/A"
            digest_input.append(
                (
                    f"Titre: {item.get('title', '')}\n"
                    f"CVE: {cve_text}\n"
                    f"Source: {item.get('source', '')}\n"
                    f"Date: {item.get('published_at', '')}\n"
                    f"Résumé: {item.get('summary', '')}\n"
                    f"Lien: {item.get('link', '')}"
                )
            )

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        messages = [
            SystemMessage(
                content=(
                    "Tu rédiges une alerte cyber en français pour une équipe sécurité. "
                    "Tu n'inventes aucune donnée et tu te limites strictement aux "
                    "éléments fournis."
                )
            ),
            HumanMessage(
                content=(
                    f"Rédige un bulletin CVE quotidien daté du {now} en Markdown "
                    "(lecture 3-5 minutes) avec:\n"
                    "1) Un résumé exécutif (3-5 points).\n"
                    "2) Une section 'Priorités immédiates' avec les vulnérabilités "
                    "les plus critiques (impact + action recommandée).\n"
                    "3) Une section 'Détails' listant chaque alerte avec source et lien.\n"
                    "4) Une section 'Actions dans les 24h'.\n"
                    "Style: opérationnel, concret, orienté remédiation.\n\n"
                    "Interdiction: n'utilise pas de tableaux Markdown, pas de colonnes, "
                    "pas de ligne contenant des '|' (pipes). Utilise uniquement des "
                    "listes à puces et des sous-titres simples.\n\n"
                    "Données:\n\n"
                    + "\n\n".join(digest_input)
                )
            ),
        ]

        try:
            response = _invoke_with_model_fallback(messages)
            digest = response.content if isinstance(response.content, str) else str(response.content)
            return {**state, "digest_markdown": digest}
        except Exception as exc:
            LOGGER.exception("Erreur génération digest cyber")
            fallback = (
                "Nouvelles alertes CVE détectées mais la synthèse automatique a échoué. "
                "Vérifie les flux source ci-dessous:\n\n"
                + "\n".join(
                    f"- {item.get('title', '')} - {item.get('link', '')}" for item in shortlisted
                )
            )
            return {
                **state,
                "digest_markdown": fallback,
                "errors": [*state.get("errors", []), f"Digest cyber fallback: {exc}"],
            }

    def notify_node(state: CyberWatchState) -> CyberWatchState:
        new_entry_ids = state.get("new_entry_ids", [])
        shortlisted_items = state.get("shortlisted_items", [])
        errors = list(state.get("errors", []))
        digest = state.get("digest_markdown", "")

        token_usage_summary: dict[str, Any] = {}
        try:
            token_usage_summary = TokenUsageStore(settings.token_usage_stats_path).record_run(
                run_usage=run_usage,
                by_model=usage_by_model,
            )
            run_stats = token_usage_summary.get("run", {})
            total_stats = token_usage_summary.get("totals", {})
            LOGGER.info(
                (
                    "Usage tokens cyber run: prompt=%s completion=%s total=%s calls=%s | "
                    "cumul: prompt=%s completion=%s total=%s runs=%s calls=%s | fichier=%s"
                ),
                run_stats.get("prompt_tokens", 0),
                run_stats.get("completion_tokens", 0),
                run_stats.get("total_tokens", 0),
                run_stats.get("llm_calls", 0),
                total_stats.get("prompt_tokens", 0),
                total_stats.get("completion_tokens", 0),
                total_stats.get("total_tokens", 0),
                total_stats.get("runs", 0),
                total_stats.get("llm_calls", 0),
                token_usage_summary.get("path", ""),
            )
        except Exception as exc:
            LOGGER.exception("Erreur suivi tokens cyber")
            errors.append(f"Token usage cyber error: {exc}")

        if not new_entry_ids:
            LOGGER.info("Aucune nouveaute cyber: aucun envoi Discord")
            return {
                **state,
                "token_usage_summary": token_usage_summary,
                "errors": errors,
                "sent": False,
            }

        if not shortlisted_items:
            seen_store.mark_seen(new_entry_ids)
            LOGGER.info(
                (
                    "Nouveautes cyber detectees (%s) mais aucune alerte prioritaire: "
                    "aucun envoi Discord"
                ),
                len(new_entry_ids),
            )
            return {
                **state,
                "token_usage_summary": token_usage_summary,
                "errors": errors,
                "sent": False,
            }

        if not digest:
            digest = "Alertes CVE prioritaires détectées, mais digest vide."

        try:
            if settings.discord_use_embeds:
                embeds = _build_cyber_embeds(
                    digest=digest,
                    shortlisted_items=shortlisted_items,
                    new_count=len(new_entry_ids),
                    token_usage_summary=token_usage_summary
                    if settings.token_usage_report_in_discord
                    else {},
                    errors=errors,
                    include_item_embeds=settings.discord_include_item_embeds,
                    item_embeds_max=settings.discord_item_embeds_max,
                )
                send_discord_embeds(
                    settings.discord_webhook_url,
                    embeds=embeds,
                    content="Alertes CVE prioritaires détectées",
                )
            else:
                payload = digest
                if settings.token_usage_report_in_discord and token_usage_summary:
                    run_stats = token_usage_summary.get("run", {})
                    total_stats = token_usage_summary.get("totals", {})
                    payload += (
                        "\n\n---\nSuivi tokens\n"
                        f"- Run: prompt={run_stats.get('prompt_tokens', 0)}, "
                        f"completion={run_stats.get('completion_tokens', 0)}, "
                        f"total={run_stats.get('total_tokens', 0)}, "
                        f"calls={run_stats.get('llm_calls', 0)}\n"
                        f"- Cumul: prompt={total_stats.get('prompt_tokens', 0)}, "
                        f"completion={total_stats.get('completion_tokens', 0)}, "
                        f"total={total_stats.get('total_tokens', 0)}, "
                        f"runs={total_stats.get('runs', 0)}, "
                        f"calls={total_stats.get('llm_calls', 0)}"
                    )

                if errors:
                    payload += (
                        "\n\n---\n⚠️ Logs techniques:\n"
                        + "\n".join(f"- {err}" for err in errors)
                    )

                send_discord_message(
                    settings.discord_webhook_url,
                    payload,
                    suppress_embeds=settings.discord_suppress_embeds,
                )
            seen_store.mark_seen(new_entry_ids)
            LOGGER.info(
                "Bulletin cyber envoye (%s alertes prioritaires / %s nouveautes)",
                len(shortlisted_items),
                len(new_entry_ids),
            )
            return {
                **state,
                "token_usage_summary": token_usage_summary,
                "errors": errors,
                "sent": True,
            }
        except Exception as exc:
            LOGGER.exception("Erreur envoi Discord cyber")
            return {
                **state,
                "token_usage_summary": token_usage_summary,
                "errors": [*errors, f"Discord cyber error: {exc}"],
                "sent": False,
            }

    graph = StateGraph(CyberWatchState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("shortlist", shortlist_node)
    graph.add_node("digest", digest_node)
    graph.add_node("notify", notify_node)

    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "shortlist")
    graph.add_edge("shortlist", "digest")
    graph.add_edge("digest", "notify")
    graph.add_edge("notify", END)

    return graph.compile()
