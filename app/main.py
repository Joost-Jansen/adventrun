"""Advent Run website: public page with progress and the pledge form, and an admin page for the owner.

The site never handles payments: people pledge here and donate on the charity's own action page afterwards.
"""

import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from starlette.middleware.sessions import SessionMiddleware

from .calc import challenge_day, euro, km_text, parse_euro_cents, parse_km, pledge_amount_cents, pledged_totals
from .config import Settings, load_settings
from .db import PLEDGE_STATUSES, Pledge, Progress, SiteSettings, make_sessionmaker
from .i18n import LANGS, MONTHS_SHORT, PATHS, format_date, format_range, translator
from .messages import STATUS_LABELS, describe, export_csv, terms
from .security import RateLimiter, check_csrf, check_origin, client_ip, csrf_token, password_ok, security_headers

HERE = Path(__file__).parent
TZ = ZoneInfo("Europe/Amsterdam")
ADMIN_SESSION_SECONDS = 12 * 3600
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{8,20}$")

LIMITS = {
    "per_km": (1, 100_00),  # €0,01 .. €100 per km
    "max": (1, 10_000_00),
    "fixed": (1_00, 10_000_00),  # €1 .. €10.000
}


def today() -> date:
    return datetime.now(TZ).date()


def calendar(start: date, days: int, today_: date, km_by_date: dict) -> list[dict]:
    """One tile per challenge day: done (the day's km or more), partial, today, past or future."""
    tiles = []
    for n in range(1, days + 1):
        d = start + timedelta(days=n - 1)
        km = km_by_date.get(d)
        if km is not None and km >= n:
            state = "done"
        elif km:
            state = "partial"
        elif d == today_:
            state = "today"
        else:
            state = "past" if d < today_ else "future"
        tiles.append({"day": n, "date": d, "km": km, "state": state, "is_today": d == today_})
    return tiles


def periods(pledges, start: date, days: int, planned_km: int, lang: str) -> list[dict]:
    """The challenge in weeks (1-7, 8-14, ... December) with what the per-km pledges bring in during each, if every
    km is run. The rows add up exactly to the per-km part of the total: each is the difference of two cumulative sums."""
    per_km = [terms(p) for p in pledges if p.type == "per_km"]
    rows, km_before, cents_before = [], 0, 0
    for first in range(1, days + 1, 7):
        last = min(first + 6, days)
        km = sum(range(first, last + 1))
        km_after = min(km_before + km, planned_km)
        cents_after = sum(pledge_amount_cents(p, km_after, planned_km) for p in per_km)
        d1, d2 = start + timedelta(days=first - 1), start + timedelta(days=last - 1)
        rows.append({"first": first, "last": last, "km": km, "cents": cents_after - cents_before, "dates": format_range(d1, d2, lang)})
        km_before, cents_before = km_after, cents_after
    return rows


def day_values(pledges, days: int, planned_km: int) -> list[tuple[int, int, int]]:
    """Per challenge day, if every day is run in full: (km by the end of that day, what the per-km pledges bring in on
    that day, what they have brought in by the end of it). Like the receipt rows, each day's value is the difference of
    two cumulative sums, so the days add up exactly."""
    per_km = [terms(p) for p in pledges if p.type == "per_km"]
    out, before = [], 0
    for n in range(1, days + 1):
        cum = min(n * (n + 1) // 2, planned_km)
        after = sum(pledge_amount_cents(p, cum, planned_km) for p in per_km)
        out.append((cum, after - before, after))
        before = after
    return out


HALF_MARATHON_KM = 21.1


def heaviness(days: int) -> dict:
    """The last seven days of the challenge: total and average per day, set against a half marathon."""
    last = list(range(max(1, days - 6), days + 1))
    total = sum(last)
    return {"last_days": len(last), "last_first": last[0], "last_km": total, "last_avg": total / len(last), "half": HALF_MARATHON_KM}


def calendar_rows(tiles: list[dict], per_row: int = 5) -> list[list[dict]]:
    return [tiles[i : i + per_row] for i in range(0, len(tiles), per_row)]


PER_KM_CHOICES = (5, 10, 25, 50, 100)  # cents per km
FIXED_CHOICES = (1000, 2500, 5000, 10000)  # cents


def amount_choices(planned_km: int, lang: str) -> dict:
    """The preset amounts on the form, each with its reference: the total at full distance, or the amount per km."""

    def input_value(cents: int) -> str:
        whole, rest = divmod(cents, 100)
        sep = "," if lang == "nl" else "."
        return f"{whole}{sep}{rest:02d}" if rest else str(whole)

    return {
        "per_km_choices": [{"value": input_value(c), "label": euro(c, lang), "total": euro(c * planned_km, lang)} for c in PER_KM_CHOICES],
        "fixed_choices": [
            {"value": input_value(c), "label": euro(c, lang), "per_km": euro(round(c / planned_km), lang)} for c in FIXED_CHOICES
        ],
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    sessions = make_sessionmaker(settings.database_url)
    pledge_limiter = RateLimiter(limit=5, window_seconds=600)
    login_limiter = RateLimiter(limit=5, window_seconds=900)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.limiters = (pledge_limiter, login_limiter)
    app.middleware("http")(security_headers(settings))
    # The session cookie is only set once someone opens the admin page; public visitors get no cookies.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="adventrun_admin",
        max_age=ADMIN_SESSION_SECONDS,
        same_site="strict",
        https_only=settings.secure_cookies,
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["euro"] = euro
    templates.env.filters["km"] = km_text
    charity = {"nl": settings.charity_name, "en": settings.charity_name_en}
    # The admin pages are Dutch; public pages pass their own `t`.
    templates.env.globals["t"] = translator("nl", settings.owner_name, charity["nl"])

    def site_context(s, lang: str = "nl") -> dict:
        cfg = s.get(SiteSettings, 1)
        planned = cfg.total_planned_km
        first, last = settings.challenge_start, settings.challenge_start + timedelta(days=settings.challenge_days - 1)
        in_challenge = Progress.date.between(first, last)  # km outside the 25 days never count
        km_walked = s.scalar(select(func.coalesce(func.sum(Progress.km), 0)).where(in_challenge)) or 0
        pledges = s.scalars(select(Pledge).where(Pledge.status != "withdrawn").order_by(Pledge.created_at, Pledge.id)).all()
        now_cents, potential_cents = pledged_totals([terms(p) for p in pledges], km_walked, planned)
        t = today()
        day = challenge_day(t, settings.challenge_start, settings.challenge_days)
        km_by_date = {r.date: r.km for r in s.scalars(select(Progress).where(in_challenge))}
        return {
            "lang": lang,
            "t": translator(lang, settings.owner_name, charity[lang]),
            "owner": settings.owner_name,
            "charity": charity[lang],
            "action_page_url": cfg.action_page_url,
            "donated_cents": cfg.donated_total_cents,
            "planned_km": planned,
            "km_walked": Decimal(str(km_walked)),
            "day": day,
            "days": settings.challenge_days,
            "start": settings.challenge_start,
            "start_text": format_date(settings.challenge_start, lang),
            "calendar": (tiles := calendar(settings.challenge_start, settings.challenge_days, t, km_by_date)),
            "day_values": day_values(pledges, settings.challenge_days, planned),
            "heavy": heaviness(settings.challenge_days),
            "calendar_rows": calendar_rows(tiles),
            "periods": periods(pledges, settings.challenge_start, settings.challenge_days, planned, lang),
            "fixed_total": sum(p.amount_cents for p in pledges if p.type == "fixed"),
            "pledged_now": now_cents,
            "pledged_potential": potential_cents,
            # What one km is worth on average: the whole pledged total spread over the km it is pledged for.
            "avg_per_km": round(now_cents / float(km_walked))
            if day > settings.challenge_days and km_walked
            else round(potential_cents / planned),
            "supporters": len(pledges),
            "wall": [p.display_name for p in pledges if p.show_name and p.display_name],
            "anonymous": sum(1 for p in pledges if not (p.show_name and p.display_name)),
        }

    def page(request: Request, name: str, lang: str, template: str, extra: dict | None = None, status_code: int = 200):
        with sessions() as s:
            ctx = site_context(s, lang)
        other = "en" if lang == "nl" else "nl"
        ctx |= {
            "page": name,
            "paths": {k: v[lang] for k, v in PATHS.items()},
            "alternates": PATHS[name],
            "other_lang": other,
            "other_lang_url": PATHS[name][other],
            "fmt": lambda cents: euro(cents, lang),
            "fmt_km": lambda km: km_text(km, lang),
            "fmt_date": lambda d: format_date(d, lang),
            # the doors show the day's number once, with the month and "km" beside it (the challenge is one month)
            "month_short": MONTHS_SHORT[lang][settings.challenge_start.month - 1],
        }
        if name == "home":
            ctx |= amount_choices(ctx["planned_km"], lang)
        return templates.TemplateResponse(request, template, ctx | (extra or {}), status_code=status_code)

    # ---- public ------------------------------------------------------------------------------------------------

    @app.get("/health")
    def health():
        return {"ok": True}

    def home_view(lang: str):
        def view(request: Request):
            return page(request, "home", lang, "index.html", {"errors": {}, "form": {"type": "per_km"}})

        return view

    def static_view(name: str, lang: str, template: str):
        def view(request: Request):
            return page(request, name, lang, template)

        return view

    for lang in LANGS:
        app.get(PATHS["home"][lang], response_class=HTMLResponse)(home_view(lang))
        app.get(PATHS["thanks"][lang], response_class=HTMLResponse)(static_view("thanks", lang, "thanks.html"))
        app.get(PATHS["privacy"][lang], response_class=HTMLResponse)(static_view("privacy", lang, "privacy.html"))

    @app.get("/en/", include_in_schema=False)
    def en_slash():
        return RedirectResponse("/en", status_code=308)

    @app.post("/toezeggen")
    def pledge(
        request: Request,
        lang: str = Form("nl"),
        display_name: str = Form(""),
        anonymous: str = Form(""),
        type: str = Form("per_km"),
        per_km_amount: str = Form(""),
        max_amount: str = Form(""),
        fixed_amount: str = Form(""),
        contact: str = Form(""),
        consent: str = Form(""),
        message: str = Form(""),
        website: str = Form(""),  # honeypot: hidden from people, filled in by bots
    ):
        lang = lang if lang in LANGS else "nl"
        t = translator(lang, settings.owner_name, charity[lang])
        check_origin(request, settings)
        if not pledge_limiter.hit(client_ip(request, settings)):
            raise HTTPException(429, t("err_rate"))
        if website:
            return RedirectResponse(PATHS["thanks"][lang], status_code=303)  # pretend it worked

        form = {
            "display_name": display_name.strip(),
            "anonymous": bool(anonymous),
            "type": type,
            "per_km_amount": per_km_amount,
            "max_amount": max_amount,
            "fixed_amount": fixed_amount,
            "contact": contact.strip(),
            "consent": bool(consent),
            "message": message.strip(),
        }
        errors: dict[str, str] = {}
        name = " ".join(form["display_name"].split())
        if len(name) > 60:
            errors["display_name"] = t("err_name_long")
        if not name and not form["anonymous"]:
            errors["display_name"] = t("err_name_required")
        amount = max_cents = None
        if type == "per_km":
            amount = parse_euro_cents(per_km_amount)
            lo, hi = LIMITS["per_km"]
            if amount is None or not lo <= amount <= hi:
                errors["per_km_amount"] = t("err_per_km")
            if max_amount.strip():
                max_cents = parse_euro_cents(max_amount)
                lo, hi = LIMITS["max"]
                if max_cents is None or not lo <= max_cents <= hi:
                    errors["max_amount"] = t("err_max")
        elif type == "fixed":
            amount = parse_euro_cents(fixed_amount)
            lo, hi = LIMITS["fixed"]
            if amount is None or not lo <= amount <= hi:
                errors["fixed_amount"] = t("err_fixed")
        else:
            errors["type"] = t("err_type")
        email = phone = None
        if form["contact"]:
            if not form["consent"]:
                errors["contact"] = t("err_consent")
            elif "@" in form["contact"]:
                if not EMAIL_RE.match(form["contact"]) or len(form["contact"]) > 254:
                    errors["contact"] = t("err_email")
                email = form["contact"]
            else:
                if not PHONE_RE.match(form["contact"]):
                    errors["contact"] = t("err_contact")
                phone = form["contact"]
        if len(form["message"]) > 500:
            errors["message"] = t("err_message")

        if errors:
            return page(request, "home", lang, "index.html", {"errors": errors, "form": form}, status_code=400)

        with sessions() as s:
            s.add(
                Pledge(
                    display_name=name,
                    show_name=not form["anonymous"],
                    type=type,
                    amount_cents=amount,
                    max_cents=max_cents if type == "per_km" else None,
                    email=email,
                    phone=phone,
                    contact_consent=bool(email or phone),
                    message=form["message"] or None,
                    lang=lang,
                )
            )
            s.commit()
        return RedirectResponse(PATHS["thanks"][lang], status_code=303)

    # ---- admin -------------------------------------------------------------------------------------------------

    def is_admin(request: Request) -> bool:
        since = request.session.get("admin_since")
        return isinstance(since, int | float) and time.time() - since < ADMIN_SESSION_SECONDS

    def require_admin(request: Request, csrf: str) -> None:
        check_origin(request, settings)
        if not is_admin(request):
            raise HTTPException(401, "not_logged_in")
        check_csrf(request, csrf)

    def back(anchor: str = "") -> RedirectResponse:
        return RedirectResponse("/admin" + anchor, status_code=303)

    @app.get("/admin", response_class=HTMLResponse)
    def admin(request: Request):
        if not is_admin(request):
            return templates.TemplateResponse(
                request, "admin/login.html", {"csrf": csrf_token(request), "error": None, "enabled": bool(settings.admin_password)}
            )
        with sessions() as s:
            ctx = site_context(s)
            pledges = s.scalars(select(Pledge).order_by(Pledge.created_at.desc(), Pledge.id.desc())).all()
            progress = s.scalars(select(Progress).order_by(Progress.date)).all()
        rows = [
            {"p": p, "describe": describe(p), "amount_now": pledge_amount_cents(terms(p), ctx["km_walked"], ctx["planned_km"])}
            for p in pledges
        ]
        return templates.TemplateResponse(
            request,
            "admin/dashboard.html",
            {
                **ctx,
                "csrf": csrf_token(request),
                "rows": rows,
                "progress": progress,
                "statuses": [(k, STATUS_LABELS[k]) for k in PLEDGE_STATUSES],
                "today": today(),
                "last_day": settings.challenge_start + timedelta(days=settings.challenge_days - 1),
            },
        )

    @app.post("/admin/login")
    def login(request: Request, password: str = Form(""), csrf: str = Form("")):
        check_origin(request, settings)
        check_csrf(request, csrf)
        if not login_limiter.hit(client_ip(request, settings)):
            raise HTTPException(429, "Te veel pogingen. Probeer het over een kwartier opnieuw.")
        if not password_ok(settings, password):
            return templates.TemplateResponse(
                request,
                "admin/login.html",
                {"csrf": csrf_token(request), "error": "Onjuist wachtwoord.", "enabled": bool(settings.admin_password)},
                status_code=401,
            )
        request.session.clear()
        request.session["admin_since"] = time.time()
        return back()

    @app.post("/admin/logout")
    def logout(request: Request, csrf: str = Form("")):
        check_origin(request, settings)
        check_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.post("/admin/settings")
    def save_settings(request: Request, csrf: str = Form(""), donated_total: str = Form(""), action_page_url: str = Form("")):
        require_admin(request, csrf)
        donated = parse_euro_cents(donated_total) if donated_total.strip() else 0
        url = action_page_url.strip()
        if donated is None or (url and not url.startswith("https://")) or len(url) > 500:
            raise HTTPException(400, "Ongeldig bedrag of link (de link moet met https:// beginnen).")
        with sessions() as s:
            cfg = s.get(SiteSettings, 1)
            cfg.donated_total_cents = donated
            cfg.action_page_url = url
            s.commit()
        return back("#instellingen")

    @app.post("/admin/progress")
    def save_progress(request: Request, csrf: str = Form(""), day: str = Form(""), km: str = Form("")):
        require_admin(request, csrf)
        try:
            d = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(400, "Ongeldige datum.")
        last_day = settings.challenge_start + timedelta(days=settings.challenge_days - 1)
        if not settings.challenge_start <= d <= last_day:
            raise HTTPException(400, f"Datum valt buiten de challenge ({settings.challenge_start.isoformat()} t/m {last_day.isoformat()}).")
        with sessions() as s:
            row = s.get(Progress, d)
            if not km.strip():
                if row:
                    s.delete(row)
            else:
                value = parse_km(km)
                if value is None:
                    raise HTTPException(400, "Ongeldig aantal km (0 tot 200).")
                if row:
                    row.km = value
                else:
                    s.add(Progress(date=d, km=value))
            s.commit()
        return back("#km")

    @app.post("/admin/pledges/{pledge_id}")
    def update_pledge(request: Request, pledge_id: int, csrf: str = Form(""), status: str = Form(""), admin_note: str = Form("")):
        require_admin(request, csrf)
        if status not in PLEDGE_STATUSES:
            raise HTTPException(400, "Ongeldige status.")
        with sessions() as s:
            p = s.get(Pledge, pledge_id)
            if p is None:
                raise HTTPException(404)
            p.status = status
            p.admin_note = admin_note.strip()[:1000]
            s.commit()
        return back(f"#p{pledge_id}")

    @app.post("/admin/pledges/{pledge_id}/delete")
    def delete_pledge(request: Request, pledge_id: int, csrf: str = Form("")):
        require_admin(request, csrf)
        with sessions() as s:
            s.execute(delete(Pledge).where(Pledge.id == pledge_id))
            s.commit()
        return back("#toezeggingen")

    @app.post("/admin/delete-all")
    def delete_all(request: Request, csrf: str = Form(""), confirm: str = Form("")):
        require_admin(request, csrf)
        if confirm.strip() != "VERWIJDER ALLES":
            raise HTTPException(400, "Typ VERWIJDER ALLES om te bevestigen.")
        with sessions() as s:
            s.execute(delete(Pledge))
            s.commit()
        return back("#toezeggingen")

    @app.get("/admin/export.csv")
    def export(request: Request):
        if not is_admin(request):
            raise HTTPException(401, "not_logged_in")
        with sessions() as s:
            ctx = site_context(s)
            pledges = s.scalars(select(Pledge).order_by(Pledge.created_at, Pledge.id)).all()
        body = export_csv(pledges, ctx["km_walked"], ctx["planned_km"], ctx["action_page_url"], settings.owner_name, charity)
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="toezeggingen-{today().isoformat()}.csv"'},
        )

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    return app
