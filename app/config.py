"""Settings from environment variables. Nothing per person or per deployment lives in code."""

import os
from dataclasses import dataclass
from datetime import date


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./adventrun.db")
    # Railway hands out postgres:// or postgresql://; SQLAlchemy needs the driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    admin_password: str
    owner_name: str
    charity_name: str
    # Origins allowed to POST (comma-separated, e.g. https://adventrun.trackerai.nl). Empty: the request's own host.
    public_origins: tuple[str, ...]
    # Behind Railway's proxy the client address is the last X-Forwarded-For entry.
    trust_proxy: bool
    # Session cookies only over HTTPS; off for local development.
    secure_cookies: bool
    challenge_start: date
    challenge_days: int


def load_settings() -> Settings:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        if os.environ.get("ENV", "development") == "production":
            raise RuntimeError("SECRET_KEY is required in production")
        secret = "dev-only-secret"
    return Settings(
        database_url=_database_url(),
        secret_key=secret,
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        owner_name=os.environ.get("OWNER_NAME", "Joost"),
        charity_name=os.environ.get("CHARITY_NAME", "het Rode Kruis"),
        public_origins=tuple(o.strip().rstrip("/") for o in os.environ.get("PUBLIC_ORIGINS", "").split(",") if o.strip()),
        trust_proxy=os.environ.get("TRUST_PROXY", "0") == "1",
        secure_cookies=os.environ.get("SECURE_COOKIES", "1" if os.environ.get("ENV") == "production" else "0") == "1",
        challenge_start=date.fromisoformat(os.environ.get("CHALLENGE_START", "2026-12-01")),
        challenge_days=int(os.environ.get("CHALLENGE_DAYS", "25")),
    )
