"""Mock Bunq — one demo user, one balance, an in-memory history.

Persistence is handled by SQLAlchemy for transactions we create through the
product itself; this module only seeds the synthetic "prior history" the
risk scorer and UI read from.

The seed encodes 6 weeks of believable spending: salary on the 25th, rent on
the 1st, twice-weekly groceries, monthly Spotify, ~weekly transport, weekday
coffees, occasional Bol.com and dinners out. This is what makes the embedding
risk classifier work — without recurring patterns, novelty is meaningless.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Transaction
from ..util import new_id

DEMO_USER_ID = "demo-user-1"
DEMO_USER_NAME = "Lena van der Berg"
DEMO_BALANCE_EUR = 4200.00


@dataclass
class User:
    id: str
    name: str
    balance_eur: float


def get_user(user_id: str = DEMO_USER_ID) -> User:
    return User(id=user_id, name=DEMO_USER_NAME, balance_eur=DEMO_BALANCE_EUR)


# Anchor "today" deterministically so the demo is reproducible regardless of
# wall-clock. Set to roughly 2026-04-25 (the doc's reference date), with the
# seed populating the preceding 6 weeks.
_TODAY = datetime(2026, 4, 24, 12, 0, 0)


def _at(days_ago: int, hh: int, mm: int) -> datetime:
    return (_TODAY - timedelta(days=days_ago)).replace(
        hour=hh, minute=mm, second=0, microsecond=0
    )


def _build_seed() -> list[dict]:
    """Six weeks of patterned history. Reproducible — same seed every run."""
    rng = random.Random(42)
    rows: list[dict] = []

    # Salary — 25th of each month (last 2 months ago, ~30 days, ~60 days)
    for d_ago in (0 + 0, 30, 60):
        # Adjust to land on actual day 25 — easier just to use offsets that
        # represent monthly cycles rather than calendar arithmetic.
        if d_ago == 0:
            continue
        rows.append({
            "merchant": "Bunq Payroll BV",
            "amount_eur": -2800.00,  # negative because outflow convention?
            # We treat amounts as outflows in the demo. Salary deposit is
            # represented as a "ghost income" event tagged with a magnitude
            # equal to the deposit; the risk model uses |amount|.
            "ts": _at(d_ago, 9, 0),
        })

    # Rent — 1st of month (approximately days 24, 54 ago given the anchor)
    for d_ago in (24, 54):
        rows.append({
            "merchant": "Stichting Woonbron",
            "amount_eur": -1150.00,
            "ts": _at(d_ago, 6, 30),
        })

    # Spotify — once per month
    for d_ago in (5, 35):
        rows.append({
            "merchant": "Spotify AB",
            "amount_eur": -10.99,
            "ts": _at(d_ago, 11, 0),
        })

    # Groceries — twice per week (Sat morning + Wed evening), 6 weeks
    # Build a regular cadence on offsets [3,6,10,13,17,20,24,27,31,34,38,41]
    grocery_offsets = [2, 5, 9, 12, 16, 19, 23, 26, 30, 33, 37, 40]
    for i, d_ago in enumerate(grocery_offsets):
        merch = "Albert Heijn" if i % 2 == 0 else "Jumbo"
        amt = -round(rng.uniform(22.0, 56.0), 2)
        hh = 10 if i % 2 == 0 else 18
        mm = rng.choice([5, 12, 27, 41, 53])
        rows.append({
            "merchant": merch,
            "amount_eur": amt,
            "ts": _at(d_ago, hh, mm),
        })

    # Public transport — ~10 trips per month, weekday mornings/evenings
    transport_offsets = [1, 2, 4, 7, 8, 11, 14, 15, 18, 21, 22, 25, 28, 29, 32, 36, 39]
    for d_ago in transport_offsets:
        merch = rng.choice(["NS Reizigers", "GVB", "GVB", "NS Reizigers"])
        amt = -round(rng.uniform(2.0, 8.5), 2)
        hh = rng.choice([8, 8, 9, 17, 18])
        mm = rng.choice([12, 24, 35, 46, 53])
        rows.append({
            "merchant": merch,
            "amount_eur": amt,
            "ts": _at(d_ago, hh, mm),
        })

    # Coffee — weekday mornings, varied small cafes
    coffee_offsets = [1, 2, 4, 7, 8, 11, 14, 15, 18, 21, 22, 25]
    for d_ago in coffee_offsets:
        merch = rng.choice(["Coffee Company", "Starbucks", "Lot Sixty One Coffee"])
        amt = -round(rng.uniform(2.8, 5.5), 2)
        rows.append({
            "merchant": merch,
            "amount_eur": amt,
            "ts": _at(d_ago, 8, rng.randint(15, 55)),
        })

    # Bol.com — 2-3 times per month
    for d_ago in (3, 16, 31):
        amt = -round(rng.uniform(15.0, 80.0), 2)
        rows.append({
            "merchant": "Bol.com",
            "amount_eur": amt,
            "ts": _at(d_ago, 13, rng.randint(0, 59)),
        })

    # Dinners out — Friday/Saturday evenings
    dinner_offsets = [3, 9, 16, 23, 30, 37]
    dinner_merchants = ["Bistro Saint Marc", "Toscanini", "Cafe de Klos", "Foodhallen"]
    for d_ago in dinner_offsets:
        rows.append({
            "merchant": rng.choice(dinner_merchants),
            "amount_eur": -round(rng.uniform(28.0, 62.0), 2),
            "ts": _at(d_ago, 20, rng.randint(0, 45)),
        })

    return rows


SEED_HISTORY = _build_seed()


def seed_if_empty() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(Transaction).limit(1))
        if existing:
            return
        for item in SEED_HISTORY:
            db.add(
                Transaction(
                    id=new_id("txn"),
                    user_id=DEMO_USER_ID,
                    amount_eur=item["amount_eur"],
                    merchant=item["merchant"],
                    tier="NO_RISK",
                    status="APPROVED",
                    merchant_reputation="GOOD",
                    created_at=item["ts"],
                )
            )
        db.commit()


def reset_all() -> None:
    from ..models import AuditLog, Ticket, Verification
    from .embedding_cache import reset as reset_embedding_cache

    with SessionLocal() as db:
        db.query(Ticket).delete()
        db.query(AuditLog).delete()
        db.query(Verification).delete()
        db.query(Transaction).delete()
        db.commit()
    reset_embedding_cache()
    seed_if_empty()
