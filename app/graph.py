from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from .config import Settings
from .discord import send_discord_message
from .models import ShortlistOutput
from .rss import collect_feed_items
from .token_usage import (
    TokenUsageStore,
    empty_usage,
    extract_usage_from_response,
    merge_usage,
)

LOGGER = logging.getLogger(__name__)


class WatchState(TypedDict):
    feed_items: list[dict[str, Any]]
    shortlisted_items: list[dict[str, Any]]
    digest_markdown: str
    token_usage_summary: dict[str, Any]
    errors: list[str]


def build_watch_graph(settings: Settings):
    active_model = settings.model_name
    run_usage = empty_usage()
    usage_by_model: dict[str, dict[str, int]] = {}

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
                        "Bascule modèle OpenAI: %s -> %s",
                        active_model,
                        model,
                    )
                active_model = model
                return result
            except Exception as exc:
                if _looks_like_model_error(exc):
                    last_model_exc = exc
                    LOGGER.warning("Modèle indisponible: %s (%s)", model, exc)
                    continue
                raise

        raise RuntimeError(
            "Aucun modèle OpenAI accessible parmi: "
            f"{', '.join(ordered_models)}. Dernière erreur: {last_model_exc}"
        )

    def fetch_node(_: WatchState) -> WatchState:
        try:
            items = collect_feed_items(settings)
            return {
                "feed_items": [item.model_dump() for item in items],
                "shortlisted_items": [],
                "digest_markdown": "",
                "token_usage_summary": {},
                "errors": [],
            }
        except Exception as exc:
            LOGGER.exception("Erreur récupération RSS")
            return {
                "feed_items": [],
                "shortlisted_items": [],
                "digest_markdown": "",
                "token_usage_summary": {},
                "errors": [f"Erreur RSS: {exc}"],
            }

    def shortlist_node(state: WatchState) -> WatchState:
        feed_items = state.get("feed_items", [])
        if not feed_items:
            return {**state, "shortlisted_items": []}

        candidates = feed_items[: settings.max_candidates]
        prompt_lines = []
        for idx, item in enumerate(candidates):
            prompt_lines.append(
                (
                    f"[{idx}] {item.get('title', '')}\n"
                    f"Source: {item.get('source', '')}\n"
                    f"Date: {item.get('published_at', '')}\n"
                    f"Résumé: {item.get('summary', '')}\n"
                    f"Lien: {item.get('link', '')}"
                )
            )

        messages = [
            SystemMessage(
                content=(
                    "Tu es un analyste de veille IA. Sélectionne les news les plus"
                    " structurantes et actionnables, en couvrant plusieurs thèmes"
                    " (LLM, agents, open-source, infra, régulation, produits)."
                    " Évite les doublons."
                )
            ),
            HumanMessage(
                content=(
                    f"Choisis exactement {settings.shortlist_size} indices\n\n"
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
                if 0 <= idx < len(candidates):
                    seen.add(idx)
                    picked.append(idx)

            if not picked:
                picked = list(range(min(settings.shortlist_size, len(candidates))))

            shortlisted = [candidates[idx] for idx in picked[: settings.shortlist_size]]
            return {**state, "shortlisted_items": shortlisted}
        except Exception as exc:
            LOGGER.exception("Erreur shortlist LLM")
            fallback = candidates[: settings.shortlist_size]
            return {
                **state,
                "shortlisted_items": fallback,
                "errors": [*state.get("errors", []), f"Shortlist fallback: {exc}"],
            }

    def digest_node(state: WatchState) -> WatchState:
        shortlisted = state.get("shortlisted_items", [])
        if not shortlisted:
            return {
                **state,
                "digest_markdown": "Aucun article pertinent trouvé aujourd'hui.",
            }

        digest_input = []
        for item in shortlisted:
            digest_input.append(
                (
                    f"Titre: {item.get('title', '')}\n"
                    f"Source: {item.get('source', '')}\n"
                    f"Date: {item.get('published_at', '')}\n"
                    f"Résumé: {item.get('summary', '')}\n"
                    f"Lien: {item.get('link', '')}"
                )
            )

        today = datetime.now().strftime("%Y-%m-%d")
        messages = [
            SystemMessage(
                content=(
                    "Tu rédiges une veille stratégique IA en français pour une"
                    " audience tech/produit. Tu n'inventes aucune info et tu te"
                    " limites aux éléments fournis."
                )
            ),
            HumanMessage(
                content=(
                    f"Rédige une note de veille datée du {today} (~10 minutes de"
                    " lecture, environ 900 à 1200 mots) au format Markdown avec:"
                    "\n1) Un TL;DR en 6 points."
                    "\n2) Les 6-10 news les plus importantes avec: pourquoi c'est"
                    " important, impact concret, et lien source."
                    "\n3) Une section 'A surveiller' (3 points)."
                    "\n4) Une section 'Liens rapides'."
                    "\nStyle: clair, dense, utile, orienté action."
                    "\n\nDonnées:\n\n"
                    + "\n\n".join(digest_input)
                )
            ),
        ]

        try:
            response = _invoke_with_model_fallback(messages)
            digest = response.content if isinstance(response.content, str) else str(response.content)
            return {**state, "digest_markdown": digest}
        except Exception as exc:
            LOGGER.exception("Erreur génération digest")
            return {
                **state,
                "digest_markdown": "Impossible de générer le digest aujourd'hui.",
                "errors": [*state.get("errors", []), f"Digest fallback: {exc}"],
            }

    def notify_node(state: WatchState) -> WatchState:
        digest = state.get("digest_markdown", "")
        errors = list(state.get("errors", []))

        if not digest:
            digest = "Aucun digest généré."

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
                    "Usage tokens run: prompt=%s completion=%s total=%s calls=%s | "
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
            LOGGER.exception("Erreur suivi tokens")
            errors.append(f"Token usage error: {exc}")

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
            payload += "\n\n---\n⚠️ Logs techniques:\n" + "\n".join(f"- {err}" for err in errors)

        try:
            send_discord_message(
                settings.discord_webhook_url,
                payload,
                suppress_embeds=settings.discord_suppress_embeds,
            )
            return {**state, "token_usage_summary": token_usage_summary, "errors": errors}
        except Exception as exc:
            LOGGER.exception("Erreur envoi Discord")
            return {
                **state,
                "token_usage_summary": token_usage_summary,
                "errors": [*errors, f"Discord error: {exc}"],
            }

    graph = StateGraph(WatchState)
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