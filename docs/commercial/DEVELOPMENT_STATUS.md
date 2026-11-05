# Commercial development checkpoint — 5 November 2026

Base: fictional family workspace branch at `5dd49db`. Work branch:
`commercial/compliance-foundation-20261105`.

## Completed

- Reviewed the existing demo and inspected the separate authenticated personal-foundation branch. Neither currently establishes commercial multi-tenancy.
- Updated the product direction to commercial SaaS, developer API subscriptions and owner administration.
- Produced a broad UK source-backed compliance baseline, including current/future/draft distinctions, jurisdiction differences and specialist scope still requiring qualification.
- Added 40 machine-readable research records. Eight records have bounded helper functions; the remaining records are research-only. No record enables live filing.
- Implemented internal tenant/staff permission contracts, API scope intersection, immutable in-memory prices and artifact/destination/environment-bound approval checks.
- Added 24 meaningful offline regression tests; all passed.

## Verification and limits

- Commercial suite: **24/24 passed** using Python 3.12 in this workspace.
- Read-only catalogue CLI: executed successfully.
- Existing fictional demo suite: **19 passed, 1 failed because Chromium is unavailable**. The failing test is `test_local_browser_review_requires_approval_and_is_idempotent`; it received the explicit browser-unavailable 503. No prototype source was changed. A ResourceWarning for an unclosed file was also emitted by the existing test run.
- No browser UI checks were completed for new commercial features; no new commercial UI exists yet.
- No production database migration, identity provider, payment integration, HTTP API or filing integration was qualified in this checkpoint.

## Next implementation work

Implement PostgreSQL tenant-scoped persistence and maintained identity integration,
then customer/API service boundaries and owner dashboard. Persist versioned pricing,
connect hosted billing in sandbox, and qualify accounting/filing modules individually.

At the initial checkpoint, work remained local. The owner subsequently authorised
GitHub commits and pushes on 5 November 2026; production deployment remains separate.

## AI/banking requirement update

Added the mandatory autonomous-agent and bank-connectivity specification. Internal
approval guards now deny agent identities and API keys; staff privileges also reject
agent actors. Three new negative permission tests bring the commercial suite to
**27/27 passing**. Extraction, agent orchestration, bank connections and human approval
UI are not implemented yet. No prototype files changed in this follow-up.

## Scheduled-development and durable-job update

The owner authorised hourly continuation and GitHub pushes. `HANDOVER.md` contains
the canonical recovery protocol; `scripts/development_checkpoint.py` performs a
read-only branch/dirty-tree/remote-divergence check after fetch. It is not a lock.

Added a durable tenant-scoped agent-job contract using SQLite for development:
idempotent batch creation, persisted progress, worker claims, expiry/reclaim and
stale-worker rejection. It does not implement the production PostgreSQL adapter,
ledger-effect exactly-once semantics or a queue worker. Future ledger operations
must have their own idempotency keys and durable/outbox boundaries.

Verification command: `cd commercial && python3 -m unittest discover -s tests`.
Current result: **32/32 passing** after correcting an INSERT placeholder mismatch
found by the first test run. No financial data, credentials or active integrations
were used. The prototype browser prerequisite limitation remains unchanged.

Next: implement production PostgreSQL repositories and maintained identity adapter;
use the durable job contract for the AI orchestration service. Before modifying a
module, inspect the current branch rather than assuming this checkpoint is newest.

## C1 PostgreSQL persistence increment — completed first slice

Scope: versioned initial PostgreSQL schema, tenant-scoped organisation/note repository,
forced row-level isolation and non-owner runtime role checks. Validate with fictional
cross-tenant reads/writes, composite references, rollback and pooled-context reuse.
No identity provider, HTTP route, filing or billing is enabled by this increment.
Recovered clean checkout at e7330e5; no unfinished task recorded or other writer found.

Implemented `commercial/migrations/0001_tenant_records.sql` and the optional
`omnixat_core.postgres` adapter: tenant/organisation/note tables, composite foreign
keys, forced RLS, principal permissions, actor attribution and transaction-local
context. Runtime roles with superuser/BYPASSRLS, table ownership/owner-role membership
or inactive RLS are rejected. Read units are database READ ONLY; exceptions roll
back; nested and ended units cannot be reused. Migration SQL/version records are
atomic, locked and checksum checked. No runtime schema/provisioning permission.

Validation on 5 November 2026:

- `cd commercial && python3 -m unittest discover -s tests -v`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  `OMNIXAT_TEST_ADMIN_DSN` pointing to a temporary local PostgreSQL **16.2** cluster:
  **22 passed**, psycopg **3.3.8**. Includes real constrained-login RLS tests,
  composite cross-tenant FK rejection, grants, persistence, rollback/reuse,
  migration repeat/checksum/failure and role-safety checks. Temporary server used
  pgserver's bundled binaries, launched over loopback TCP; no production DB used.
- Initial integration run exposed a test-fixture ownership/grant restoration issue;
  corrected fixture and reran the complete integration suite successfully.
- `cd prototype && python3 -m unittest discover -s tests -v`: **19 passed, 1 failed**
  at the unchanged Chromium-dependent browser test (503 Chromium unavailable).
  Existing unclosed-file ResourceWarning also appeared. No prototype code changed.
- `git diff --check`: passed. No new commercial UI, browser or live adapter tested.

Boundaries: trusted Principal remains an internal input, not authenticated identity.
RLS protects missing query predicates, not a compromised runtime able to set tenant
context. Persistent membership/revocation, entity grants, complete audit, production
DB version/restore qualification and HTTP surfaces remain unfinished. Note creation
is not idempotent; do not describe it as exactly-once ledger posting. Existing
SQLite jobs are still a development adapter. No bank, billing, filing or model
connection was enabled. See `commercial/POSTGRES.md` for setup and test prerequisites.

Next resumable increment: persistent memberships with revocation and maintained
identity verification feeding a trusted Principal; then shared customer/API services.
Keep the current PostgreSQL schema and RLS regression suite as the starting point.
No active/unfinished implementation remains in this increment.

## C1 membership and token verification — completed second slice

Recovered clean c547e53 checkout, no recorded unfinished increment or active writer.
Scope: additive persistent identity/membership/revocation migration; maintained
PyJWT RS256 access-token verification with pinned issuer/audience/public keys;
transaction-bound membership lookup feeding existing record services. No role,
staff, MFA or agent elevation from token claims. No login UI, live provider setup,
filing, payment or bank integration. Test signed fictional tokens and real PostgreSQL.

Implemented additive `0002_identity_memberships.sql`, `identity.py` and
`identity_postgres.py`. Access tokens use maintained PyJWT with pinned RSA public
keys/issuer/audience and a bounded RFC 9068 profile. Persistent identity/membership
lookup occurs in the same scoped transaction as record work. Database role/actor
kind override untrusted claims; no staff/MFA grants are inferred. Fixed records-only
bearer scopes preserve the human filing-approval boundary. Revocation, identity
disable, issue-time cutoff and role downgrade are checked on each new unit of work.
Original migration 0001 is unchanged; upgrade preservation has a PostgreSQL test.

Verification on 5 November 2026 (Python 3.12):

- `cd commercial && python3 -m unittest discover -s tests -v`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -v`: **9 passed**;
  generated-in-memory RSA signing keys, signature/algorithm/type/key-source attacks,
  issuer/audience/time/required-claim checks and explicit trusted key rotation.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable local PostgreSQL 16.2 through `OMNIXAT_TEST_ADMIN_DSN`: **37 passed**.
  Includes the original 22 cases, 14 membership/token-to-record cases, and legacy
  schema upgrade preservation. PyJWT 2.13.0, cryptography 50.0.0, psycopg 3.3.8.
- `cd prototype && python3 -m unittest discover -s tests -v`: **19 passed, 1 failed**
  at the unchanged browser test with explicit Chromium-unavailable 503. Existing
  unclosed-file ResourceWarning appeared. No demo source or test was removed/skipped.
- `git diff --check`: passed. No live provider, customer data or signing keys used.

Limits: this is a verified resource-token/membership adapter, not a completed
maintained-provider login deployment. No provider selected/activated, discovery/JWKS
refresh, HTTP route, browser session, PKCE/CSRF, recovery or MFA step-up implemented.
Revocation applies to the next unit; an in-flight transaction is not cancelled and
token expiry is checked on entry. Add bounded request/transaction lifetimes at the
transport. Runtime membership tables are SELECT only; administrative provisioning,
revocation UI/audit and entity grants remain to build. No idempotent ledger effects,
statutory submission, bank connection or billing was enabled.

Next resumable increment: shared authenticated customer/API transport with bounded
transactions and controlled error responses, and qualify a maintained-provider login
flow separately. See `commercial/IDENTITY.md`. No active task remains in this slice.

## C2 authenticated records transport — completed first slice

Recovered clean c95521a; no unfinished task or competing writer found. Scope:
bearer-only versioned ASGI organisation/note endpoints calling shared authenticated
record services; explicit hosts/HTTPS, bounded JSON intake, generic errors, scoped
connections and database transaction time controls. Test signed fictional tokens
through HTTP against real PostgreSQL. No login, billing, bank or filing route.

Implemented `http_api.create_app`: development ASGI routes for creating/reading
organisations and attributed notes through existing signed-token/membership services.
No server/listener starts on import. Explicit host/HTTPS checks, bearer-only auth,
strict single-field JSON, actual body-byte limit, five-second body deadline,
generic error envelopes and generated request IDs. No token/SQL/payload diagnostics
returned. Query tokens, role spoofing and unsupported idempotency headers cannot
bypass authority. Runtime connections exit before success; no automatic retry.

Shared record transactions now use local statement 5s, lock 1s and idle 5s limits,
plus a monotonic ten-second pre-commit check. Exceeded work rolls back. This is not
a hard wall-time cancellation guarantee; acquisition, concurrency and server/network
limits still require hosting configuration. No database migration was modified.

Verification on 5 November 2026:

- `cd commercial && python3 -m unittest discover -s tests -v`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -v`: **9 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  `OMNIXAT_TEST_ADMIN_DSN` for temporary local PostgreSQL 16.2: **58 passed**.
  Includes 18 HTTP tests using genuine signed fictional tokens/constrained DB
  connections, three time-control tests and all previous 37 cases. Checks real
  persistence, cross-tenant access/linking, membership revocation, roles/scopes,
  strict/duplicate/streamed/slow/oversized body handling, errors, closure and rollback.
- Exercised Starlette 1.6.0, httpx 0.28.1, psycopg 3.3.8, PyJWT 2.13.0, Python 3.12.
  Starlette's httpx TestClient emits a deprecation warning recommending httpx2.
  No warning suppressed. No network/TLS/browser hosting qualification completed.
- `cd prototype && python3 -m unittest discover -s tests -v`: **19 passed, 1 failed**
  at unchanged Chromium-unavailable browser test (503). Existing ResourceWarning
  appeared. No demo code/test changed or skipped.
- `git diff --check`: passed. Only intended code/tests/docs and optional requirements.

Limits: no live identity provider/login, public deployment, quotas, owner UI,
entity grants, complete audit, document extraction, bank, billing, filing or
approval route. Creation remains non-idempotent; unsupported request keys are
rejected explicitly. Unknown POST outcomes must be reconciled, not auto-retried.

Next resumable increment: durable tenant/operation/payload-bound creation keys and
result reconciliation with minimal audit events before autonomous write retries;
maintained-provider browser login qualification remains separate unfinished work.
Read `commercial/HTTP_API.md`. No active task remains in this increment.

## C2 durable creation receipts — completed

Recovered clean ddb78cd. Scope: append-only PostgreSQL creation receipts for
organisation/note writes, optional request keys scoped to workspace, actor and
operation, payload conflict detection and same-transaction replay. Test concurrency,
rollback, replay authorization and HTTP validation. No external effects or deployment.

Migration 0003 adds append-only creation receipts with tenant/actor row isolation,
deferred tenant-bound result foreign keys and a unique scope for keyed creations.
Shared organisation/note writes commit the receipt and result together. An optional
Idempotency-Key yields the existing result on an exact replay, or 409 for changed
valid inputs. Replay rechecks authority; an unkeyed POST remains a separate write.
Only metadata and optional digests are retained in receipts. No historical backfill,
automatic retry, expiry job, audit dashboard or external-effect guarantee.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **9 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **68 passed**, including two-connection
  contention/replay, rollback, tenant/actor/operation isolation, changed parent/body,
  audit grants, legacy migration, HTTP header validation and revoked replay.
  Existing Starlette test-client deprecation warning remains.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**
  at the unchanged browser lab test (Chromium unavailable). No test skipped.
- `git diff --check`: passed. No production, billing, bank or filing action.

Next: persist versioned plans/prices and authorised owner audit in a separate
sandbox-ready billing increment, without activating payments. Maintained-provider
login, entity grants, audit access/retention and API quotas remain open. The
creation receipt is a PostgreSQL record-write contract, not a ledger effect or
filing receipt. No active work remains in this increment.
