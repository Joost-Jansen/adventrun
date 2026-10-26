import csv
import io
import re
from datetime import date

from sqlalchemy import create_engine, inspect, text

from app.db import make_sessionmaker
from app.i18n import PATHS, T
from app.main import calendar

from .conftest import ORIGIN, login


def test_every_key_in_both_languages():
    assert T["nl"].keys() == T["en"].keys()
    for key in T["nl"]:
        assert set(re.findall(r"\{(\w+)\}", T["nl"][key])) == set(re.findall(r"\{(\w+)\}", T["en"][key])), key


def test_english_pages(client):
    for name, path in ((k, v["en"]) for k, v in PATHS.items()):
        r = client.get(path)
        assert r.status_code == 200, name
        assert '<html lang="en">' in r.text
    home = client.get("/en").text
    assert "Or make a pledge" in home and "Wall of support" in home and "the Red Cross" in home
    assert 'hreflang="nl" href="/"' in home
    assert client.get("/en/", follow_redirects=False).headers["location"] == "/en"


def test_dutch_home_links_to_english(client):
    body = client.get("/").text
    assert '<html lang="nl">' in body and 'href="/en"' in body and "Of doe een toezegging" in body


def test_english_pledge_redirects_and_errors_in_english(client, app):
    base = {"lang": "en", "display_name": "Alex", "type": "fixed", "fixed_amount": "25"}
    r = client.post("/toezeggen", data=base, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/en/thanks"
    r = client.post("/toezeggen", data={**base, "fixed_amount": "0.5"}, headers=ORIGIN)
    assert r.status_code == 400 and "Enter an amount between" in r.text and '<html lang="en">' in r.text


def test_unknown_lang_falls_back_to_dutch(client):
    r = client.post("/toezeggen", data={"lang": "xx", "display_name": "A", "per_km_amount": "0,10"}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/bedankt"


def test_csv_message_in_pledge_language(client):
    client.post("/toezeggen", data={"lang": "en", "display_name": "Alex", "type": "per_km", "per_km_amount": "0.10"}, headers=ORIGIN)
    client.post("/toezeggen", data={"lang": "nl", "display_name": "Sanne", "type": "per_km", "per_km_amount": "0,10"}, headers=ORIGIN)
    login(client)
    rows = list(csv.reader(io.StringIO(client.get("/admin/export.csv").text.lstrip("﻿")), delimiter=";"))
    header = rows[0]
    msgs = {r[header.index("naam")]: r[header.index("berichttekst")] for r in rows[1:]}
    assert msgs["Alex"].startswith("Hi Alex") and "the Red Cross" in msgs["Alex"]
    assert msgs["Sanne"].startswith("Hoi Sanne") and "het Rode Kruis" in msgs["Sanne"]


def test_preset_amounts_show_their_reference(client):
    nl = client.get("/").text
    assert "€ 32,50 totaal" in nl  # €0,10 per km over 325 km
    assert "≈ € 0,08 per km" in nl  # €25 fixed
    en = client.get("/en").text
    assert "€32.50 in total" in en and "≈ €0.08 per km" in en


def test_migration_adds_lang_to_existing_table(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    with create_engine(url).begin() as conn:
        conn.execute(
            text("CREATE TABLE pledges (id INTEGER PRIMARY KEY, display_name VARCHAR(60), type VARCHAR(10), amount_cents INTEGER)")
        )
        conn.execute(text("INSERT INTO pledges (display_name, type, amount_cents) VALUES ('Oud', 'fixed', 500)"))
    make_sessionmaker(url)
    engine = create_engine(url)
    assert "lang" in {c["name"] for c in inspect(engine).get_columns("pledges")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT lang FROM pledges")).scalar() == "nl"


def test_calendar_states():
    start = date(2026, 12, 1)
    tiles = calendar(start, 25, date(2026, 12, 4), {date(2026, 12, 1): 1, date(2026, 12, 2): 1})
    assert [t["state"] for t in tiles[:5]] == ["done", "partial", "past", "today", "future"]
    assert tiles[3]["is_today"]
