"""Tables and the database connection. Separate from the health tracker: only totals per day, no health data."""

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

PLEDGE_TYPES = ("per_km", "fixed")
PLEDGE_STATUSES = ("pledged", "reminded", "donated", "withdrawn")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Pledge(Base):
    __tablename__ = "pledges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    display_name: Mapped[str] = mapped_column(String(60), default="")
    show_name: Mapped[bool] = mapped_column(Boolean, default=True)
    type: Mapped[str] = mapped_column(String(10))
    # Per km: cents per km. Fixed: the whole amount in cents.
    amount_cents: Mapped[int] = mapped_column(Integer)
    max_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pledged")
    admin_note: Mapped[str] = mapped_column(Text, default="")
    # The language the pledge was made in ("nl" | "en"), for the message afterwards.
    lang: Mapped[str] = mapped_column(String(2), default="nl", server_default="nl")


class Progress(Base):
    __tablename__ = "progress"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    km: Mapped[float] = mapped_column(Numeric(5, 2))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SiteSettings(Base):
    """A single row (id 1)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    donated_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    action_page_url: Mapped[str] = mapped_column(String(500), default="")
    total_planned_km: Mapped[int] = mapped_column(Integer, default=325)


def _migrate(engine) -> None:
    """Columns added after the first deploy: create_all does not add them to an existing table."""
    columns = {c["name"] for c in inspect(engine).get_columns("pledges")}
    if "lang" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE pledges ADD COLUMN lang VARCHAR(2) NOT NULL DEFAULT 'nl'"))


def make_sessionmaker(database_url: str) -> sessionmaker:
    kwargs = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(database_url, **kwargs)
    Base.metadata.create_all(engine)
    _migrate(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        if s.get(SiteSettings, 1) is None:
            s.add(SiteSettings(id=1))
            s.commit()
    return factory
