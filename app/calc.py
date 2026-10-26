"""The calculation rules (PROJECT.md, section 8). Pure functions, so they are easy to test.

pledged_now       = sum(fixed) + sum(min(per_km * km_walked, max))
pledged_potential = sum(fixed) + sum(min(per_km * total_planned_km, max))

km_walked is capped at the planned total: running further than planned never makes a pledge larger than its owner
expected. Withdrawn pledges count for nothing.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class PledgeTerms:
    type: str  # "per_km" | "fixed"
    amount_cents: int
    max_cents: int | None = None
    status: str = "pledged"


def counted_km(km_walked: Decimal | float | int, total_planned_km: int) -> Decimal:
    km = Decimal(str(km_walked))
    return max(Decimal(0), min(km, Decimal(total_planned_km)))


def pledge_amount_cents(p: PledgeTerms, km: Decimal | float | int, total_planned_km: int) -> int:
    if p.status == "withdrawn":
        return 0
    if p.type == "fixed":
        return p.amount_cents
    cents = (Decimal(p.amount_cents) * counted_km(km, total_planned_km)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    amount = int(cents)
    if p.max_cents is not None:
        amount = min(amount, p.max_cents)
    return amount


def pledged_totals(pledges: list[PledgeTerms], km_walked, total_planned_km: int) -> tuple[int, int]:
    """(now, potential) in cents."""
    now = sum(pledge_amount_cents(p, km_walked, total_planned_km) for p in pledges)
    potential = sum(pledge_amount_cents(p, total_planned_km, total_planned_km) for p in pledges)
    return now, potential


def challenge_day(today: date, start: date, days: int) -> int:
    """0 before the start, 1..days during, days + 1 after."""
    n = (today - start).days + 1
    if n < 1:
        return 0
    return min(n, days + 1)


def euro(cents: int) -> str:
    """€ 1.234,56 in Dutch notation; whole euros without decimals."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    whole, rest = divmod(cents, 100)
    whole_s = f"{whole:,}".replace(",", ".")
    return f"{sign}€\u00a0{whole_s}" if rest == 0 else f"{sign}€\u00a0{whole_s},{rest:02d}"


def km_text(km) -> str:
    d = Decimal(str(km)).normalize()
    s = f"{d:f}"
    return s.replace(".", ",")


def parse_euro_cents(text: str) -> int | None:
    """'0,10', '0.10', '€ 5', '1.000,50' -> cents. None when not a valid amount."""
    t = (text or "").strip().replace("€", "").replace(" ", "").replace("\u00a0", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        value = Decimal(t)
    except ArithmeticError:
        return None
    if not value.is_finite() or value < 0:
        return None
    cents = (value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if cents != value * 100:
        return None  # fractions of a cent
    return int(cents)


def parse_km(text: str) -> Decimal | None:
    t = (text or "").strip().replace(",", ".")
    try:
        value = Decimal(t)
    except ArithmeticError:
        return None
    if not value.is_finite() or value < 0 or value > 200:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
