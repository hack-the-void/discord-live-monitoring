from __future__ import annotations

import logging

from app.cyber_runner import run_cyber_watch_once


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    result = run_cyber_watch_once()

    new_count = len(result.get("new_entry_ids", []))
    sent = bool(result.get("sent", False))
    print("\n=== Check Cyber termine ===\n")
    print(f"Nouveaux items detectes: {new_count}")
    print(f"Message envoye: {sent}")

    if sent:
        print("\n=== Bulletin Cyber genere ===\n")
        print(result.get("digest_markdown", ""))