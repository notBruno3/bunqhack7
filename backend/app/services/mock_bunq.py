"""Mock Bunq — one demo user, one balance, an in-memory history.

Persistence is handled by SQLAlchemy for transactions we create through the
product itself; this module only seeds the synthetic "prior history" the
risk scorer and UI read from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

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


SEED_HISTORY = [
    {"amount_eur": 38.20, "merchant": "Albert Heijn", "days_ago": 1},
    {"amount_eur": 12.50, "merchant": "Spotify", "days_ago": 4},
    {"amount_eur": 62.00, "merchant": "Jumbo", "days_ago": 7},
    {"amount_eur": 210.00, "merchant": "Bol.com", "days_ago": 14},
    {"amount_eur": 19.99, "merchant": "Uber", "days_ago": 21},
]


def seed_if_empty() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(Transaction).limit(1))
        if existing:
            return
        now = datetime.utcnow()
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
                    created_at=now - timedelta(days=item["days_ago"]),
                )
            )
        db.commit()


def reset_all() -> None:
    from ..models import AuditLog, Ticket, Verification

    with SessionLocal() as db:
        db.query(Ticket).delete()
        db.query(AuditLog).delete()
        db.query(Verification).delete()
        db.query(Transaction).delete()
        db.commit()
    seed_if_empty()
