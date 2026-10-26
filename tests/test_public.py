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
    assert "Doe een toezegging" in r.text
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
    assert "+ 1 anoniem" in body
    assert "0,37" not in body


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
    """€1 per km at 0 km: the big number is €325 (all 325 km), with €0 so far underneath."""
    post(client, per_km_amount="1")
    body = client.get("/").text
    assert '<p class="value">€ 325</p>' in body
    assert "Tot nu toe: € 0 bij 0 km" in body
    en = client.get("/en").text
    assert '<p class="value">€325</p>' in en and "So far: €0 at 0 km" in en
