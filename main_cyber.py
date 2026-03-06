from __future__ import annotations

import logging

from app.cyber_scheduler import start_hourly_cyber_scheduler


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    start_hourly_cyber_scheduler()