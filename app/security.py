"""Security headers, origin check for every POST, a small in-memory rate limiter and the admin CSRF token."""

import hmac
import secrets
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from .config import Settings

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)


def security_headers(settings: Settings):
    async def middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return middleware


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # The proxy appends the address it saw; anything to the left of it can be forged by the client.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def check_origin(request: Request, settings: Settings) -> None:
    """Reject cross-site POSTs (CSRF). Browsers send Origin on every POST; fall back to Referer."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        raise HTTPException(403, "origin_missing")
    parts = urlsplit(source)
    origin = f"{parts.scheme}://{parts.netloc}"
    if settings.public_origins:
        if origin not in settings.public_origins:
            raise HTTPException(403, "origin_mismatch")
    elif parts.netloc != request.headers.get("host", ""):
        raise HTTPException(403, "origin_mismatch")


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Record a hit; False when the key is over its limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:  # keep memory bounded
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, submitted or ""):
        raise HTTPException(403, "csrf_invalid")


def password_ok(settings: Settings, submitted: str) -> bool:
    if not settings.admin_password:
        return False  # admin is off until ADMIN_PASSWORD is set
    return hmac.compare_digest(settings.admin_password.encode(), (submitted or "").encode())
