from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import load_settings
from .runner import run_watch_once

LOGGER = logging.getLogger(__name__)


def start_daily_scheduler() -> None:
    settings = load_settings()

    scheduler = BlockingScheduler(timezone=settings.timezone)

    def _job() -> None:
        LOGGER.info("Lancement du digest quotidien")
        try:
            run_watch_once(settings)
        except Exception:
            LOGGER.exception("Le job quotidien a échoué")

    scheduler.add_job(
        _job,
        trigger="cron",
        hour=settings.run_hour,
        minute=settings.run_minute,
        id="daily_ai_watch",
        replace_existing=True,
    )

    LOGGER.info(
        "Scheduler démarré. Prochaine exécution chaque jour à %02d:%02d (%s)",
        settings.run_hour,
        settings.run_minute,
        settings.timezone,
    )
    scheduler.start()