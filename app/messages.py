"""The personal thank-you and reminder text per supporter, and the CSV export."""

import csv
import io

from .calc import PledgeTerms, counted_km, euro, km_text, pledge_amount_cents
from .db import Pledge

STATUS_LABELS = {"pledged": "toegezegd", "reminded": "herinnerd", "donated": "gedoneerd", "withdrawn": "ingetrokken"}


def terms(p: Pledge) -> PledgeTerms:
    return PledgeTerms(type=p.type, amount_cents=p.amount_cents, max_cents=p.max_cents, status=p.status)


def describe(p: Pledge) -> str:
    if p.type == "fixed":
        return f"{euro(p.amount_cents)} vast"
    s = f"{euro(p.amount_cents)} per km"
    if p.max_cents is not None:
        s += f", max. {euro(p.max_cents)}"
    return s


def personal_message(p: Pledge, km_walked, total_planned_km: int, action_page_url: str, owner_name: str, charity: dict[str, str]) -> str:
    """The text to send after the challenge, in the language the pledge was made in. charity: name per language."""
    lang = "en" if p.lang == "en" else "nl"
    km = km_text(counted_km(km_walked, total_planned_km), lang)
    amount = euro(pledge_amount_cents(terms(p), km_walked, total_planned_km), lang)
    name = p.display_name.strip()
    if lang == "en":
        per_km = f"{euro(p.amount_cents, 'en')} per km" + (f", max. {euro(p.max_cents, 'en')}" if p.max_cents is not None else "")
        basis = f"You pledged {amount}." if p.type == "fixed" else f"With your pledge of {per_km}, that comes to {amount}."
        return (
            f"Hi {name or 'there'},\n\n"
            f"Thank you so much for supporting my advent run. I ran {km} km in December. {basis}\n\n"
            f"Would you donate that amount on the fundraising page of {charity['en']} before 1 January? "
            f"{action_page_url or '[link to the fundraising page]'}\n\n"
            f"The money goes straight to {charity['en']}, not through me. Happy holidays!\n\n{owner_name}"
        )
    basis = f"Je had {amount} toegezegd." if p.type == "fixed" else f"Met jouw toezegging van {describe(p)} komt dat uit op {amount}."
    return (
        f"Hoi {name or 'daar'},\n\n"
        f"Heel erg bedankt voor je steun aan mijn adventsloop. Ik heb in december {km} km gelopen. {basis}\n\n"
        f"Wil je dat bedrag vóór 1 januari doneren op de actiepagina van {charity['nl']}? "
        f"{action_page_url or '[link naar de actiepagina]'}\n\n"
        f"Het geld gaat rechtstreeks naar {charity['nl']}, niet via mij. Fijne feestdagen!\n\n{owner_name}"
    )


def _cell(value) -> str:
    """Neutralise spreadsheet formulas (CSV injection)."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(
    pledges: list[Pledge], km_walked, total_planned_km: int, action_page_url: str, owner_name: str, charity: dict[str, str]
) -> str:
    out = io.StringIO()
    out.write("\ufeff")  # Excel reads UTF-8 with a BOM
    w = csv.writer(out, delimiter=";")
    w.writerow(
        [
            "id",
            "datum",
            "naam",
            "naam tonen",
            "soort",
            "toezegging",
            "e-mail",
            "telefoon",
            "status",
            "bedrag (euro)",
            "taal",
            "bericht",
            "notitie",
            "berichttekst",
        ]
    )
    for p in pledges:
        cents = pledge_amount_cents(terms(p), km_walked, total_planned_km)
        w.writerow(
            [
                _cell(x)
                for x in (
                    p.id,
                    p.created_at.date().isoformat() if p.created_at else "",
                    p.display_name,
                    "ja" if p.show_name else "nee",
                    "per km" if p.type == "per_km" else "vast",
                    describe(p),
                    p.email,
                    p.phone,
                    STATUS_LABELS.get(p.status, p.status),
                    f"{cents // 100},{cents % 100:02d}",
                    p.lang,
                    p.message,
                    p.admin_note,
                    personal_message(p, km_walked, total_planned_km, action_page_url, owner_name, charity),
                )
            ]
        )
    return out.getvalue()
