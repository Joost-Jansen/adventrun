from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def settings(tmp_path):
    return replace(
        load_settings(),
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="test-secret",
        admin_password="correct horse battery staple",
        public_origins=(),
        challenge_start=date(2026, 12, 1),
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def login(client) -> str:
    page = client.get("/admin").text
    csrf = page.split('name="csrf" value="')[1].split('"')[0]
    r = client.post("/admin/login", data={"password": "correct horse battery staple", "csrf": csrf}, headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin").text
    return page.split('name="csrf" value="')[1].split('"')[0]
