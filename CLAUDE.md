# For agents

Read [PROJECT.md](PROJECT.md) first (Dutch): it is the brief, the decisions and the log. Keep it up to date: change the
relevant section with every decision and add a line to the log at the bottom. Talk to Joost in Dutch; code, comments
and commits in English, the UI in Dutch and English.

- FastAPI with server-rendered Jinja templates, no frontend build. SQLAlchemy; Postgres on Railway, SQLite locally.
- The site never handles payments and never shows contact details, messages or amounts per person in public pages.
- Public pages are bilingual (`app/i18n.py`, Dutch on `/`, English on `/en`): every public text needs both; `tests/test_i18n.py` checks it. Admin stays Dutch.
- No per-person or per-deployment values in code: they come from environment variables (`.env.example`).
- The CSP allows no inline script or style: put JS in `app/static/*.js`, CSS in `app/static/style.css`.
- Before pushing: `ruff check .`, `ruff format --check .`, `python -m pytest -q`.
