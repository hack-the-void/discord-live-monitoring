from __future__ import annotations

import logging

from app.scheduler import start_daily_scheduler


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    start_daily_scheduler()