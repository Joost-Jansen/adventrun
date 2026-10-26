"""Advent Run website: public page with progress and the pledge form, and an admin page for the owner.

The site never handles payments: people pledge here and donate on the charity's own action page afterwards.
"""

import re
import time
from datetime import date, datetime
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

    def site_context(s) -> dict:
        cfg = s.get(SiteSettings, 1)
        planned = cfg.total_planned_km
        km_walked = s.scalar(select(func.coalesce(func.sum(Progress.km), 0))) or 0
        pledges = s.scalars(select(Pledge).where(Pledge.status != "withdrawn").order_by(Pledge.created_at, Pledge.id)).all()
        now_cents, potential_cents = pledged_totals([terms(p) for p in pledges], km_walked, planned)
        t = today()
        day = challenge_day(t, settings.challenge_start, settings.challenge_days)
        today_row = s.get(Progress, t)
        return {
            "owner": settings.owner_name,
            "charity": settings.charity_name,
            "action_page_url": cfg.action_page_url,
            "donated_cents": cfg.donated_total_cents,
            "planned_km": planned,
            "km_walked": Decimal(str(km_walked)),
            "km_percent": min(100, round(float(km_walked) / planned * 100)) if planned else 0,
            "km_today": today_row.km if today_row else None,
            "day": day,
            "days": settings.challenge_days,
            "start": settings.challenge_start,
            "pledged_now": now_cents,
            "pledged_potential": potential_cents,
            "supporters": len(pledges),
            "wall": [p.display_name for p in pledges if p.show_name and p.display_name],
            "anonymous": sum(1 for p in pledges if not (p.show_name and p.display_name)),
        }

    # ---- public ------------------------------------------------------------------------------------------------

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with sessions() as s:
            ctx = site_context(s)
        return templates.TemplateResponse(request, "index.html", {**ctx, "errors": {}, "form": {"type": "per_km"}})

    @app.post("/toezeggen")
    def pledge(
        request: Request,
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
        check_origin(request, settings)
        if not pledge_limiter.hit(client_ip(request, settings)):
            raise HTTPException(429, "Te veel toezeggingen achter elkaar. Probeer het over een paar minuten opnieuw.")
        if website:
            return RedirectResponse("/bedankt", status_code=303)  # pretend it worked

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
            errors["display_name"] = "Maximaal 60 tekens."
        if not name and not form["anonymous"]:
            errors["display_name"] = "Vul een naam of bijnaam in, of kies anoniem."
        amount = max_cents = None
        if type == "per_km":
            amount = parse_euro_cents(per_km_amount)
            lo, hi = LIMITS["per_km"]
            if amount is None or not lo <= amount <= hi:
                errors["per_km_amount"] = "Vul een bedrag per km in, tussen € 0,01 en € 100."
            if max_amount.strip():
                max_cents = parse_euro_cents(max_amount)
                lo, hi = LIMITS["max"]
                if max_cents is None or not lo <= max_cents <= hi:
                    errors["max_amount"] = "Vul een maximum in tussen € 0,01 en € 10.000, of laat het leeg."
        elif type == "fixed":
            amount = parse_euro_cents(fixed_amount)
            lo, hi = LIMITS["fixed"]
            if amount is None or not lo <= amount <= hi:
                errors["fixed_amount"] = "Vul een bedrag in tussen € 1 en € 10.000."
        else:
            errors["type"] = "Kies per km of een vast bedrag."
        email = phone = None
        if form["contact"]:
            if not form["consent"]:
                errors["contact"] = "Vink toestemming aan, of laat dit veld leeg. Zonder toestemming bewaar ik geen contactgegevens."
            elif "@" in form["contact"]:
                if not EMAIL_RE.match(form["contact"]) or len(form["contact"]) > 254:
                    errors["contact"] = "Dit lijkt geen geldig e-mailadres."
                email = form["contact"]
            else:
                if not PHONE_RE.match(form["contact"]):
                    errors["contact"] = "Vul een geldig e-mailadres of telefoonnummer in."
                phone = form["contact"]
        if len(form["message"]) > 500:
            errors["message"] = "Maximaal 500 tekens."

        if errors:
            with sessions() as s:
                ctx = site_context(s)
            return templates.TemplateResponse(request, "index.html", {**ctx, "errors": errors, "form": form}, status_code=400)

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
                )
            )
            s.commit()
        return RedirectResponse("/bedankt", status_code=303)

    @app.get("/bedankt", response_class=HTMLResponse)
    def thanks(request: Request):
        with sessions() as s:
            ctx = site_context(s)
        return templates.TemplateResponse(request, "thanks.html", ctx)

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        with sessions() as s:
            ctx = site_context(s)
        return templates.TemplateResponse(request, "privacy.html", ctx)

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
        body = export_csv(pledges, ctx["km_walked"], ctx["planned_km"], ctx["action_page_url"], settings.owner_name, settings.charity_name)
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="toezeggingen-{today().isoformat()}.csv"'},
        )

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    return app
