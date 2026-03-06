from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import load_cyber_settings
from .cyber_runner import run_cyber_watch_once

LOGGER = logging.getLogger(__name__)


def start_hourly_cyber_scheduler() -> None:
    settings = load_cyber_settings()
    scheduler = BlockingScheduler(timezone=settings.timezone)

    def _job() -> None:
        LOGGER.info("Lancement du check cyber horaire")
        try:
            run_cyber_watch_once(settings)
        except Exception:
            LOGGER.exception("Le job cyber horaire a echoue")

    scheduler.add_job(
        _job,
        trigger="cron",
        hour="*",
        minute=settings.run_minute,
        id="hourly_cyber_watch",
        replace_existing=True,
    )

    LOGGER.info(
        "Scheduler cyber demarre. Execution chaque heure a HH:%02d (%s)",
        settings.run_minute,
        settings.timezone,
    )
    scheduler.start()