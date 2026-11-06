# Commercial foundation — development slice C0

This is **working internal Python domain code**, not a deployable SaaS or filing service. It is separate from the fictional family demo. Python 3.11+; the offline core has no third-party dependencies. The optional PostgreSQL adapter uses psycopg.

```bash
cd commercial
python3 -m unittest discover -s tests -v
python3 -m omnixat_core
```

Implemented:

- Tenant permission and staff permission checks, with separate API scopes and MFA requirements.
- Immutable, versioned in-memory price catalogue; new versions preserve old subscription references.
- Artifact/destination/environment-bound approval integrity helpers.
- Agent identities cannot approve filings; API keys cannot replace human review.
- Durable, tenant-scoped agent-job checkpoints with idempotency and expiring worker
  claims, using a SQLite development adapter. Production PostgreSQL remains to build.
- Bounded ordinary private-company/SA deadlines, MTD threshold screening and cumulative standard update dates.
- Historic/current nominal micro-threshold lookup and revised-replacement completeness checks.
- Dated source catalogue with explicit research-only versus bounded-function support.

**Important boundaries:** No login/session implementation, production-qualified HTTP hosting, complete production tenant-isolation qualification, billing collection, owner dashboard, filing submission, tax calculation or authoritative filing status is provided by this slice. `Principal` must come from a trusted identity adapter, never customer-supplied role headers. The in-memory pricing spike remains for offline use; see the staff PostgreSQL catalogue below. Approval helpers are not a complete approval service: entity/ruleset binding, persistence, expiry/revocation and live release qualification are still required.

Rule functions are narrow helpers, not full applicability engines. Special deadlines, calendar MTD elections, two-year/group/transition eligibility, continuing mandation and authority overrides remain to implement. Recheck current rules before using these helpers in a released product. No real financial data or credentials are required to run the tests.

See [commercial specification](../docs/commercial/COMMERCIAL_SPEC.md) and [research baseline](../docs/commercial/UK_COMPLIANCE_RESEARCH_2026-11-05.md).

The [AI and banking specification](../docs/commercial/AI_AND_BANKING_SPEC.md)
defines autonomous bookkeeping, evidence intake, clarification, reconciliation
and business bank connectivity. These workflows are requirements, not implemented
connectors. After adding human-only approval guards, the core suite passes 27 tests.

## PostgreSQL record persistence

The optional [PostgreSQL adapter](POSTGRES.md) now provides versioned migrations,
forced tenant RLS, composite organisation/note references and attributed record
operations in isolated transactions. Its **22 PostgreSQL integration tests** and
the **32 offline core tests** pass. Complete provider login integration, entity grants,
production restoration/security qualification and PostgreSQL job persistence remain
unfinished. This does not make the commercial platform deployable.

## Signed identity and persistent memberships

[Identity adapter](IDENTITY.md): additive identity/membership schema, signed bearer
verification with pinned issuer/audience/public keys, and persisted role/revocation
lookup feeding the same record services. Token role/MFA/staff/actor claims cannot
elevate database authority; bearer tokens cannot approve filings. Current checks:
**32 core + 9 identity + 37 PostgreSQL tests pass**. No browser login, provider
onboarding or complete production identity qualification exists yet. See the development HTTP slice below.

## Authenticated record HTTP transport

The [development ASGI API](HTTP_API.md) now exposes versioned organisation/note
create/read routes through the same bearer/membership services, with strict JSON,
body/time controls and generic errors. Current checks: **32 core + 9 token + 91
PostgreSQL/HTTP integration tests pass**. No server starts on import. Keyed creation retries now return the original record and successful creates
record a minimal audit receipt. Audit access/retention, quotas, login, hosting and
all live integrations remain unfinished. No approval/submission route exists in this API.

## Persistent staff pricing

The [PostgreSQL price catalogue](PRICING.md) adds plans, scheduled GBP versions
and a bounded owner audit in a separate database schema. It preserves old version
IDs and has no payment connection.

## Subscription sandbox

The [internal subscription sandbox](SUBSCRIPTION_SANDBOX.md) pins price versions
and validates trial, pending, expired and cancelled states in tenant-isolated
PostgreSQL storage. It exposes no HTTP route and cannot activate billing.

[Local simulator receipts](SANDBOX_EVENTS.md) verify and deduplicate signed
snapshots and record mismatches without applying a billing state change.

[Owner sandbox metrics](SANDBOX_METRICS.md) provide an internal, read-only
aggregate of sandbox subscriptions and simulator receipts. No customer data or
live revenue appears in the snapshot.

The [staff identity boundary](STAFF_IDENTITY.md) verifies a profiled staff ID
token and checks separate PostgreSQL membership and revocation. No browser
callback, session or staff route is wired.

[One-time staff login transactions](STAFF_LOGIN.md) add PostgreSQL replay
protection and browser-bound PKCE material for a future OIDC callback.

[Revocable staff sessions](STAFF_SESSIONS.md) are short-lived PostgreSQL sessions
with fresh role, MFA and revocation checks. The browser transport is unwired.

The [Keycloak staff adapter](KEYCLOAK_STAFF.md) connects these services to a
pinned code exchange tested with a fictional provider. No realm or route is live.

The same [Keycloak guide](KEYCLOAK_STAFF.md#offline-realm-preflight) describes a
credential-free check of saved discovery metadata and approved signing keys.

[Staff authentication cleanup](STAFF_AUTH_CLEANUP.md) removes expired login
attempts and sessions in bounded operator batches.

The [staff browser qualification app](STAFF_BROWSER.md) can be constructed
explicitly for isolated testing. It is not mounted by the customer API.

The [staff browser admission hook](STAFF_BROWSER.md#shared-qualification-limits)
shares qualification rate limits across workers through PostgreSQL.

The [evidence registry](EVIDENCE.md) records document fingerprints and minimal
metadata with organisation-scoped duplicate detection. An internal local
quarantine spool computes fingerprints from bounded streams. The internal
PostgreSQL quarantine can retain matching originals. A separate worker can record
verdicts from a trusted scanner callback using recoverable PostgreSQL claims.
A separate read gate checks the active scan policy before releasing an original
to trusted worker code. An internal CSV reader returns source-linked decimal candidates; no real scanner,
OCR, model or upload route is wired.
