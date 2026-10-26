import re

from sqlalchemy import select

from app.db import Pledge

from .conftest import ORIGIN


def pledges(app):
    with app.state.sessions() as s:
        return s.scalars(select(Pledge)).all()


def post(client, **data):
    base = {"display_name": "Sanne", "type": "per_km", "per_km_amount": "0,10"}
    return client.post("/toezeggen", data={**base, **data}, headers=ORIGIN, follow_redirects=False)


def test_home_renders_without_cookies(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Of doe een toezegging" in r.text
    assert "Doneer nu direct" not in r.text and "De link naar de actiepagina komt hier" in r.text  # no action page set yet
    assert "set-cookie" not in r.headers
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_pledge_per_km_is_stored(client, app):
    r = post(client, max_amount="20")
    assert r.status_code == 303 and r.headers["location"] == "/bedankt"
    [p] = pledges(app)
    assert (p.type, p.amount_cents, p.max_cents, p.display_name) == ("per_km", 10, 2000, "Sanne")


def test_fixed_pledge(client, app):
    assert post(client, type="fixed", fixed_amount="25").status_code == 303
    [p] = pledges(app)
    assert (p.type, p.amount_cents, p.max_cents) == ("fixed", 2500, None)


def test_contact_without_consent_is_not_stored(client, app):
    r = post(client, contact="sanne@example.com")
    assert r.status_code == 400
    assert pledges(app) == []


def test_contact_with_consent_is_stored_but_never_public(client, app):
    assert post(client, contact="sanne@example.com", consent="1", message="Zet hem op!").status_code == 303
    [p] = pledges(app)
    assert p.email == "sanne@example.com" and p.contact_consent
    for page in ("/", "/bedankt", "/privacy"):
        body = client.get(page).text
        assert "sanne@example.com" not in body
        assert "Zet hem op!" not in body


def test_phone_contact(client, app):
    assert post(client, contact="+31 6 12345678", consent="1").status_code == 303
    assert pledges(app)[0].phone == "+31 6 12345678"


def test_wall_shows_names_without_amounts(client):
    post(client, display_name="Sanne", per_km_amount="0,37")
    post(client, display_name="Geheim", anonymous="1")
    body = client.get("/").text
    assert "Sanne" in body
    assert "Geheim" not in body
    assert "en 1 anoniem" in body
    wall = body[body.index('id="muur"') : body.index("</div>", body.index('id="muur"'))]
    assert "0,37" not in wall and "€" not in wall


def test_invalid_amount_is_rejected(client, app):
    assert post(client, per_km_amount="").status_code == 400
    assert post(client, per_km_amount="1000").status_code == 400
    assert post(client, type="fixed", fixed_amount="0,50").status_code == 400
    assert post(client, type="other").status_code == 400
    assert pledges(app) == []


def test_name_or_anonymous_required(client, app):
    assert post(client, display_name="").status_code == 400
    assert post(client, display_name="", anonymous="1").status_code == 303


def test_honeypot_stores_nothing(client, app):
    assert post(client, website="http://spam").status_code == 303
    assert pledges(app) == []


def test_cross_site_post_is_refused(client, app):
    r = client.post("/toezeggen", data={"display_name": "x", "per_km_amount": "1"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/toezeggen", data={"display_name": "x", "per_km_amount": "1"})
    assert r.status_code == 403
    assert pledges(app) == []


def test_rate_limit(client):
    for _ in range(5):
        assert post(client).status_code == 303
    assert post(client).status_code == 429


def test_headline_pledged_is_full_distance_before_the_end(client):
    """€1 per km at 0 km: the big number is €325 (all 325 km), with €0 so far."""
    post(client, per_km_amount="1")
    body = client.get("/").text
    assert 'aria-describedby="receipt-note">€\u00a0325</p>' in body
    assert "<dt>tot nu toe, 0 km</dt><dd>€\u00a00</dd>" in body
    en = client.get("/en").text
    assert 'aria-describedby="receipt-note">€325</p>' in en and "<dt>so far, 0 km</dt><dd>€0</dd>" in en


def test_receipt_rows_add_up_to_the_total(client):
    post(client, display_name="A", per_km_amount="1", max_amount="100")  # capped at 100 during week 2
    post(client, display_name="B", per_km_amount="0,10")  # 32,50 over 325 km
    post(client, display_name="C", type="fixed", fixed_amount="25")
    body = client.get("/").text
    rows = re.findall(r'<li><span>(.*?)</span><span class="dots" aria-hidden="true"></span><span class="num">(.*?)</span></li>', body)
    assert rows == [
        ("1–7 december · 28 km", "€\u00a030,80"),  # 28 + 2,80
        ("8–14 december · 77 km", "€\u00a079,70"),  # A reaches its maximum: 72 + 7,70
        ("15–21 december · 126 km", "€\u00a012,60"),
        ("22–25 december · 94 km", "€\u00a09,40"),
        ("Vaste bedragen", "€\u00a025"),
    ]
    assert '<span>Samen</span><span class="num">€\u00a0157,50</span>' in body  # 30,80 + 79,70 + 12,60 + 9,40 + 25
    assert 'Muur van steun <span class="count">3</span>' in body


def test_average_per_km(client):
    post(client, display_name="A", per_km_amount="1")  # 325 at full distance
    post(client, display_name="B", type="fixed", fixed_amount="65")  # 65
    body = client.get("/").text
    assert "<dt>gemiddeld per km</dt><dd>€\u00a01,20</dd>" in body  # 390 / 325
    assert "<dt>toezeggingen</dt><dd>2</dd>" in body
    assert "per km on average" in client.get("/en").text


def test_calendar_doors_carry_their_details(client):
    post(client, per_km_amount="1")
    post(client, display_name="Kim", type="fixed", fixed_amount="25")
    body = client.get("/").text
    # day 21: the shortest day; €21 that day (€1 × 21 km), 231 km by then, €231 + €25 fixed pledged by then
    pop = body[body.index('<span class="pop-head">21 december') :]
    pop = pop[: pop.index('<span class="door-inside"')]
    assert "21 december · 21 km · Kortste dag van het jaar" in pop
    assert '<span class="pop-num">€\u00a021</span><span class="pop-label">toegezegd voor deze dag</span>' in pop
    assert '<span class="pop-num">231 km</span><span class="pop-label">gelopen tot en met deze dag</span>' in pop
    assert '<span class="pop-num">€\u00a0256</span><span class="pop-label">toegezegd tot en met deze dag</span>' in pop
    assert '<span class="pop-head">21 December · 21 km · Shortest day of the year</span>' in client.get("/en").text


def test_heaviness_section(client):
    body = client.get("/").text
    assert "In de laatste 7 dagen loop ik 154 km: gemiddeld 22 km per dag, meer dan een halve marathon" in body
    assert "halve marathon · 21,1 km" in body
    assert body.count('class="bar h') == 25
    assert body.count(" is-heavy") == 7
    assert "Waarom het Rode Kruis" in body


def test_doors_show_date_and_km_and_open_onto_the_amount(client):
    post(client, per_km_amount="0,50")
    body = client.get("/").text
    # day 25: "25 dec" and "25 km" on the door, €12,50 behind it (€0,50 × 25 km)
    assert '<span class="door-inside" aria-hidden="true">€\u00a012,50</span>' in body
    assert '<span class="door-num">25</span><span class="door-units"><span>dec</span><span>km</span></span>' in body
    assert "<span>Dec</span><span>km</span>" in client.get("/en").text


def test_goal_in_receipt_and_chart(settings):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app

    c = TestClient(create_app(replace(settings, goal_per_km_cents=325)))
    c.post("/toezeggen", data={"display_name": "A", "type": "per_km", "per_km_amount": "1"}, headers=ORIGIN)
    body = c.get("/").text
    assert "Doel: €\u00a01.056,25 (€\u00a03,25 per km)" in body  # 3,25 × 325 km
    assert "31% van het doel toegezegd" in body  # 325 / 1056,25
    assert "nog nodig €\u00a0731,25" in body
    assert 'class="goal-ref"' in body and "doel €\u00a01.056,25" in body
    assert 'class="money-line"' in body and "€\u00a0325 op 25 dec" in body


def test_no_goal_without_setting(client):
    body = client.get("/").text
    assert "Doel:" not in body and 'class="goal-ref"' not in body
    assert 'class="money-line"' in body  # the line still shows what has been pledged


def test_owner_photo_only_when_set(settings):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app

    assert 'class="avatar"' not in TestClient(create_app(replace(settings, owner_photo=""))).get("/").text
    body = TestClient(create_app(replace(settings, owner_photo="/static/img/owner.webp"))).get("/").text
    assert '<img src="/static/img/owner.webp" alt="Joost"' in body and "loopt voor het Rode Kruis" in body


def test_action_page_from_environment(settings):
    """ACTION_PAGE_URL works until the admin sets a link: fixed amounts go straight there."""
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app

    body = TestClient(create_app(replace(settings, action_page_url="https://example.org/actie"))).get("/en").text
    assert '<a class="choice choice-link" href="https://example.org/actie"' in body and 'value="fixed"' not in body
    assert ">Donate now</a>" in body
