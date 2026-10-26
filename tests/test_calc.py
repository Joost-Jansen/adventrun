from datetime import date
from decimal import Decimal

from app.calc import PledgeTerms, challenge_day, euro, parse_euro_cents, parse_km, pledge_amount_cents, pledged_totals

PER_KM = PledgeTerms("per_km", 10)  # €0,10 per km
PER_KM_MAX = PledgeTerms("per_km", 25, max_cents=2000)  # €0,25 per km, max €20
FIXED = PledgeTerms("fixed", 1500)


def test_per_km_without_max():
    assert pledge_amount_cents(PER_KM, 0, 325) == 0
    assert pledge_amount_cents(PER_KM, 100, 325) == 1000
    assert pledge_amount_cents(PER_KM, 325, 325) == 3250


def test_per_km_with_max():
    assert pledge_amount_cents(PER_KM_MAX, 0, 325) == 0
    assert pledge_amount_cents(PER_KM_MAX, 40, 325) == 1000
    assert pledge_amount_cents(PER_KM_MAX, 80, 325) == 2000
    assert pledge_amount_cents(PER_KM_MAX, 325, 325) == 2000


def test_fixed_regardless_of_km():
    assert pledge_amount_cents(FIXED, 0, 325) == 1500
    assert pledge_amount_cents(FIXED, 325, 325) == 1500


def test_km_beyond_plan_is_capped():
    assert pledge_amount_cents(PER_KM, 340, 325) == 3250


def test_fractional_km_rounds_half_up():
    assert pledge_amount_cents(PledgeTerms("per_km", 5), Decimal("12.3"), 325) == 62  # 61.5 -> 62


def test_withdrawn_counts_nothing():
    assert pledge_amount_cents(PledgeTerms("fixed", 1500, status="withdrawn"), 325, 325) == 0


def test_totals_now_and_potential():
    now, potential = pledged_totals([PER_KM, PER_KM_MAX, FIXED], 28, 325)
    assert now == 280 + 700 + 1500
    assert potential == 3250 + 2000 + 1500


def test_challenge_day():
    start = date(2026, 12, 1)
    assert challenge_day(date(2026, 11, 30), start, 25) == 0
    assert challenge_day(date(2026, 12, 1), start, 25) == 1
    assert challenge_day(date(2026, 12, 25), start, 25) == 25
    assert challenge_day(date(2026, 12, 26), start, 25) == 26


def test_parse_euro():
    assert parse_euro_cents("0,10") == 10
    assert parse_euro_cents("0.10") == 10
    assert parse_euro_cents("€ 5") == 500
    assert parse_euro_cents("1.000,50") == 100050
    assert parse_euro_cents("0,005") is None
    assert parse_euro_cents("abc") is None
    assert parse_euro_cents("-1") is None
    assert parse_euro_cents("NaN") is None


def test_parse_km():
    assert parse_km("12,5") == Decimal("12.50")
    assert parse_km("-1") is None
    assert parse_km("x") is None


def test_euro_format():
    assert euro(3250) == "€\u00a032,50"
    assert euro(32500) == "€\u00a0325"
    assert euro(123456700) == "€\u00a01.234.567"
