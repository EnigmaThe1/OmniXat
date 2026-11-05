# Security model (alpha)

**Data classification:** Public company lookup + user-entered tax-applicability flags. **Do not enter bank statements, passwords for government services, UTRs, NI numbers or real tax records yet.**

## Controls included

- Browser UI exposed only on Docker host loopback (127.0.0.1).
- Backend and PostgreSQL never publish host ports.
- Unique owner password (16+ characters) and unique HMAC signing secret (32+).
- Signed HTTP-only session cookie, SameSite=Strict, 12-hour max age.
- Custom write-request header required to prevent basic cross-site form submission.
- Login throttled per observed client IP (best-effort in-process).
- Input validation, safe Companies House request paths, short HTTP timeout and sanitised API errors.
- No credentials returned from session/status endpoints.
- Minimal audit events of configuration mutations.
- No API for actual filings or tax payments.

## Known limitations and release blockers

- Owner password currently read from a local environment variable (not an Argon2id password hash).
- No TLS, 2FA, back-up encryption, authenticated remote access or persistent distributed login rate limit.
- SQLAlchemy `create_all` instead of database migrations.
- Limited tests and no external penetration test.
- No confirmed government production credentials or submission verification.
- No deletion/reversal flows or reconciled filing-status tracking.
- Some due dates may not apply because special cases and HMRC notices take precedence.
- Public source code: NEVER commit local .env, secrets, personal data or real documents.

**Before real financial documents:** Argon2id, migrations, encryption at rest, secure backups + restoration tests, revised threat model, upload malware screening and complete audit history.

**Before remote access:** TLS, MFA/passkeys, proper host/origin enforcement, persistent rate limits and hardened reverse proxy.

**Before a real tax submission:** formal entitlement and identity checks, deterministic computations, legal declarations, owner approval, official acknowledgements, idempotency, and independent validation.
