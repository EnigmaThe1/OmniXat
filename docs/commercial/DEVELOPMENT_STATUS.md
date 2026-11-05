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
