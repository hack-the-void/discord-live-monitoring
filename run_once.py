from __future__ import annotations

import logging

from app.runner import run_watch_once


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    digest = run_watch_once()
    print("\n=== Digest généré ===\n")
    print(digest)