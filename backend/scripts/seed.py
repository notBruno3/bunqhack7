"""Seed the demo user + transaction history.

Runs implicitly at startup via services.mock_bunq.seed_if_empty();
this script is a manual trigger for when you want to wipe and reseed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_db  # noqa: E402
from app.services import mock_bunq  # noqa: E402


def main() -> None:
    init_db()
    mock_bunq.reset_all()
    print("Seeded demo user + history.")


if __name__ == "__main__":
    main()
