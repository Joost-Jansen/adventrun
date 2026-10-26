import csv
import io

from sqlalchemy import select

from app.db import Pledge

from .conftest import ORIGIN, login


def add(client, **data):
    base = {"display_name": "Sanne", "type": "per_km", "per_km_amount": "0,10"}
    client.post("/toezeggen", data={**base, **data}, headers=ORIGIN)


def test_admin_requires_login(client):
    r = client.get("/admin")
    assert "Wachtwoord" in r.text
    assert client.get("/admin/export.csv").status_code == 401
    assert client.post("/admin/delete-all", data={"confirm": "VERWIJDER ALLES"}, headers=ORIGIN).status_code == 401


def test_wrong_password(client):
    page = client.get("/admin").text
    csrf = page.split('name="csrf" value="')[1].split('"')[0]
    r = client.post("/admin/login", data={"password": "nope", "csrf": csrf}, headers=ORIGIN)
    assert r.status_code == 401


def test_admin_disabled_without_password(settings):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app

    c = TestClient(create_app(replace(settings, admin_password="")))
    assert "ADMIN_PASSWORD" in c.get("/admin").text


def test_new_pledge_shows_in_admin_with_contact(client):
    add(client, contact="sanne@example.com", consent="1", message="Succes!")
    login(client)
    body = client.get("/admin").text
    assert "sanne@example.com" in body and "Succes!" in body


def test_csrf_required(client):
    login(client)
    r = client.post("/admin/progress", data={"day": "2026-12-01", "km": "1", "csrf": "wrong"}, headers=ORIGIN)
    assert r.status_code == 403


def test_progress_updates_totals_and_csv(client, app):
    add(client, display_name="Sanne", per_km_amount="0,10", contact="sanne@example.com", consent="1")
    add(client, display_name="Piet", per_km_amount="0,25", max_amount="20")
    add(client, display_name="Kim", type="fixed", fixed_amount="15")
    csrf = login(client)
    for day, km in (("2026-12-01", "1"), ("2026-12-02", "2"), ("2026-12-03", "3,5")):
        assert (
            client.post("/admin/progress", data={"day": day, "km": km, "csrf": csrf}, headers=ORIGIN, follow_redirects=False).status_code
            == 303
        )
    client.post(
        "/admin/settings", data={"donated_total": "12,50", "action_page_url": "https://example.org/actie", "csrf": csrf}, headers=ORIGIN
    )

    home = client.get("/").text
    assert "6,5" in home
    # 6.5 km: 0.65 + 1.625 (-> 1.63) + 15
    assert "€\u00a017,28" in home
    assert "€\u00a012,50" in home
    # the direct-donation button sits above the pledge form and goes to the action page
    assert '<a class="button button-candle" href="https://example.org/actie" rel="noopener" target="_blank">Doneer nu direct</a>' in home
    assert home.index("Doneer nu direct") < home.index("Of doe een toezegging") < home.index('id="pledge-form"')

    rows = list(csv.reader(io.StringIO(client.get("/admin/export.csv").text.lstrip("\ufeff")), delimiter=";"))
    header, data = rows[0], rows[1:]
    amounts = {r[header.index("naam")]: r[header.index("bedrag (euro)")] for r in data}
    assert amounts == {"Sanne": "0,65", "Piet": "1,63", "Kim": "15,00"}
    sanne = next(r for r in data if r[header.index("naam")] == "Sanne")
    assert "6,5 km" in sanne[header.index("berichttekst")]
    assert "https://example.org/actie" in sanne[header.index("berichttekst")]

    # Clearing a day removes it
    client.post("/admin/progress", data={"day": "2026-12-03", "km": "", "csrf": csrf}, headers=ORIGIN)
    assert "3 van 325" in client.get("/").text


def test_full_distance_csv(client):
    add(client, display_name="Piet", per_km_amount="0,25", max_amount="20")
    add(client, display_name="Sanne", per_km_amount="0,10")
    csrf = login(client)
    for d in range(1, 26):
        client.post("/admin/progress", data={"day": f"2026-12-{d:02d}", "km": str(d), "csrf": csrf}, headers=ORIGIN)
    rows = list(csv.reader(io.StringIO(client.get("/admin/export.csv").text.lstrip("\ufeff")), delimiter=";"))
    header = rows[0]
    amounts = {r[header.index("naam")]: r[header.index("bedrag (euro)")] for r in rows[1:]}
    assert amounts == {"Piet": "20,00", "Sanne": "32,50"}


def test_csv_neutralises_formulas(client):
    add(client, display_name="=HYPERLINK(1)")
    login(client)
    assert "'=HYPERLINK(1)" in client.get("/admin/export.csv").text


def test_status_and_delete(client, app):
    add(client, display_name="Sanne")
    add(client, display_name="Piet")
    csrf = login(client)
    with app.state.sessions() as s:
        sanne, piet = s.scalars(select(Pledge).order_by(Pledge.id)).all()
    client.post(f"/admin/pledges/{sanne.id}", data={"status": "withdrawn", "admin_note": "", "csrf": csrf}, headers=ORIGIN)
    assert "Sanne" not in client.get("/").text
    client.post(f"/admin/pledges/{piet.id}/delete", data={"csrf": csrf}, headers=ORIGIN)
    with app.state.sessions() as s:
        assert [p.display_name for p in s.scalars(select(Pledge))] == ["Sanne"]


def test_delete_all_needs_confirmation(client, app):
    add(client)
    add(client, display_name="Piet")
    csrf = login(client)
    assert client.post("/admin/delete-all", data={"confirm": "ja", "csrf": csrf}, headers=ORIGIN).status_code == 400
    assert (
        client.post(
            "/admin/delete-all", data={"confirm": "VERWIJDER ALLES", "csrf": csrf}, headers=ORIGIN, follow_redirects=False
        ).status_code
        == 303
    )
    with app.state.sessions() as s:
        assert s.scalars(select(Pledge)).all() == []


def test_settings_rejects_non_https_link(client):
    csrf = login(client)
    r = client.post("/admin/settings", data={"donated_total": "0", "action_page_url": "javascript:alert(1)", "csrf": csrf}, headers=ORIGIN)
    assert r.status_code == 400


def test_km_outside_the_challenge_are_refused(client):
    csrf = login(client)
    for day in ("2026-11-30", "2026-12-26"):
        r = client.post("/admin/progress", data={"day": day, "km": "10", "csrf": csrf}, headers=ORIGIN)
        assert r.status_code == 400 and "buiten de challenge" in r.text
    assert "0 van 325 km" in client.get("/").text
