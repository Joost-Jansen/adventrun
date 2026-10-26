# Adventsloop

Website for the Advent Run Challenge: from 1 to 25 December Joost runs the day's number in km (325 km in total) for the
Red Cross. People pledge per km or a fixed amount here; afterwards they donate on the charity's own action page. The
site never handles money. Brief, decisions and phases: [PROJECT.md](PROJECT.md).

## Run locally

```sh
pip install -r requirements-dev.txt
ADMIN_PASSWORD=dev uvicorn app.main:create_app --factory --reload
python -m pytest -q
```

Open http://localhost:8000 and http://localhost:8000/admin.

## Deploy on Railway

1. New project, then **Deploy from GitHub repo**, and pick this repository. Railway reads `railway.json` and builds the
   `Dockerfile`; the healthcheck is `/health`.
2. Add a **PostgreSQL** database to the project and wait until it is running. Then, in the web service variables, set
   `DATABASE_URL` to `${{Postgres.DATABASE_URL}}` (a reference set before the Postgres service exists stays empty).
3. Set the other variables:

   | Variable | Value |
   |---|---|
   | `ENV` | `production` |
   | `SECRET_KEY` | a long random string (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
   | `ADMIN_PASSWORD` | a long password; the admin page is off without it |
   | `TRUST_PROXY` | `1` |
   | `PUBLIC_ORIGINS` | `https://<service>.up.railway.app` (later also the custom domain, comma-separated) |
   | `GOAL_PER_KM` | optional fundraising goal per km, e.g. `3,25` (the goal shown is this times the planned km); empty shows no goal |
   | `OWNER_NAME`, `CHARITY_NAME`, `CHARITY_NAME_EN` | optional, default `Joost`, `het Rode Kruis` and `the Red Cross` |
   | `OWNER_PHOTO` | optional, path or URL of the round photo, default `/static/img/owner.webp`; empty shows none |

4. Pick an EU region (e.g. Amsterdam) for both services. **Settings, Networking, Generate Domain** gives a `*.up.railway.app` address. A custom domain is added later
   (phase 4): add it in Railway and create the CNAME it shows at the DNS provider.

Keep one replica: the rate limits live in memory.
