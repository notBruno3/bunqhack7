from __future__ import annotations

from ..schemas import MerchantReputation

GOOD = {
    "Albert Heijn",
    "Jumbo",
    "Etsy",
    "Ticketmaster",
    "Booking.com",
    "KLM",
    "Apple",
    "Spotify",
    "Bol.com",
    "Uber",
}

BAD = {
    "Unknown LLP",
    "QuickCash Transfer",
    "Crypto Vault Ltd",
    "Offshore Holdings",
    "FastWire",
}


def lookup(merchant: str) -> MerchantReputation:
    name = merchant.strip()
    if name in GOOD:
        return "GOOD"
    if name in BAD:
        return "BAD"
    return "UNKNOWN"
