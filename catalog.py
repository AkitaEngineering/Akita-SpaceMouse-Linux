# SPDX-License-Identifier: GPL-3.0-only
"""Service SKUs for Akita SpaceMouse for Linux.

ASM-LNX-CE is the Community Edition. It is not a sold licence. The SKUs below
are paid work. Nothing in this catalog disables the software.
"""

from dataclasses import dataclass


SOFTWARE_MODEL = "ASM-LNX-CE"
CAPPED_KINDS = frozenset({"setup", "hourly", "subscription"})


@dataclass(frozen=True)
class Sku:
    code: str
    kind: str
    region: str
    currency: str
    minor: int
    seats: int | None
    minutes: int
    default_days: int
    term: str
    name: str

    @property
    def price(self) -> str:
        return format_money(self.minor, self.currency)


def format_money(minor: int, currency: str) -> str:
    symbol = {"USD": "US$", "CAD": "C$", "EUR": "€"}[currency]
    whole, cents = divmod(minor, 100)
    amount = f"{whole:,}"
    if cents:
        amount = f"{amount}.{cents:02d}"
    return f"{symbol}{amount}"


def _service(kind, name, term, days, seats, minutes, prices):
    codes = {"US": "US", "CA": "CA", "EU": "EU"}
    currencies = {"US": "USD", "CA": "CAD", "EU": "EUR"}
    prefix = {
        "setup": "ASM-SET-1",
        "hourly": "ASM-SUP-H",
        "pilot": "ASM-FLT-5",
        "rollout": "ASM-ROL-1",
        "subscription": "ASM-SUB-10",
    }[kind]
    return tuple(
        Sku(f"{prefix}-{codes[region]}", kind, region, currencies[region], minor, seats, minutes, days, term, name)
        for region, minor in prices.items()
    )


CATALOG = (
    *_service("setup", "Remote setup, one workstation, up to 45 minutes", "the service date", 1, 1, 45,
              {"US": 10900, "CA": 14900, "EU": 9900}),
    *_service("hourly", "On-demand troubleshooting, one hour", "12 months", 365, None, 60,
              {"US": 14900, "CA": 16900, "EU": 11900}),
    *_service("pilot", "Fleet pilot, up to five workstations", "90 days", 90, 5, 0,
              {"US": 49900, "CA": 64900, "EU": 44900}),
    *_service("rollout", "Assisted rollout, one additional workstation", "90 days", 90, 1, 0,
              {"US": 3900, "CA": 4900, "EU": 3900}),
    *_service("subscription", "Monthly team support, up to ten workstations", "one calendar month", 0, 10, 60,
              {"US": 14900, "CA": 19900, "EU": 13900}),
)
SKUS = {sku.code: sku for sku in CATALOG}


def hourly_sku(region: str) -> Sku:
    for sku in CATALOG:
        if sku.region == region and sku.kind == "hourly":
            return sku
    raise KeyError(region)
