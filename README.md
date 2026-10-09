# OmniXat — personal-first UK tax control centre

**Status: milestone 0.1 code on a development branch; full builds and integration tests are pending.** Private, self-hosted single-owner application. This is **not** yet accounting software, a tax calculator, or a filing service. It cannot submit returns, pay HMRC, or determine whether you are legally required to file.

## What works in 0.1

- Owner-password login with signed, HTTP-only, SameSite=Strict cookie and write-request anti-CSRF header.
- Locally hosted browser dashboard and read-only compliance calendar.
- Multiple limited-company records, with optional verified Companies House lookup and refresh.
- Manual company records clearly flagged **unverified**, without invented Companies House deadlines.
- User-confirmed Self Assessment tax-year entries and standard 31 January online deadline.
- Optional second payment on account date, only when explicitly selected.
- User-supplied HMRC Corporation Tax period end, with standard CT600 and payment dates; special cases explicitly caveated.
- Audit entries for configuration changes.
- PostgreSQL storage and Docker Compose health checks; web exposed on localhost only.
- Python tests for key deadline and security behaviours.

**Important:** Calendar dates do not prove that a return is outstanding or already filed. No HMRC credentials, bank feeds, AI accounting or official filing functions exist yet.

## Run locally (Ubuntu / Linux + Docker Compose)

```bash
git clone https://github.com/EnigmaThe1/OmniXat.git
cd OmniXat
git switch feat/personal-foundation
cp .env.example .env
chmod 600 .env
# Edit .env and set three DIFFERENT random values:
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
# Put those in POSTGRES_PASSWORD, OMNIXAT_OWNER_PASSWORD, OMNIXAT_SESSION_SECRET.
# Optional: obtain a free Companies House developer API key and set COMPANIES_HOUSE_API_KEY.
docker compose up --build -d
docker compose ps
```

Then open **http://127.0.0.1:3000** and sign in using the password you configured.

This alpha binds the browser UI to **127.0.0.1 only**. Do not expose port 3000 through a reverse proxy or the internet; remote access, TLS, MFA and hardening are future milestones.

### Obtain optional company lookup credentials

See [Companies House Developer Hub](https://developer.company-information.service.gov.uk/) for an API key. Store it **only in .env**, never in a committed file. Manual company profiles work without it.

### Test backend

```bash
cd apps/api
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

### Troubleshooting

- Startup fails with missing secrets: replace the blank values in `.env`. Owner password must be 16+ characters; session signing key 32+ characters.
- Company lookup unavailable: configure a valid Companies House key, then `docker compose up -d --force-recreate api`.
- Database unavailable: `docker compose ps` and `docker compose logs db`.
- This release uses initial schema creation (not migrations); do **not** use real financial records yet.
- You can stop with `docker compose down`; persistent database stays in `db_data`. Do not run `down -v` if you wish to keep the database.

## Development standards

See [Architecture](docs/ARCHITECTURE.md), [Security](docs/SECURITY.md), and [Roadmap](docs/ROADMAP.md).

No secrets, identifiable personal data, tax identifiers or real financial records belong in this **public GitHub repository**.

## Licensing

A public repository is not automatically open-source licensed. No licence has been selected yet; contributors should not assume permission to redistribute or reuse this code beyond applicable law.
