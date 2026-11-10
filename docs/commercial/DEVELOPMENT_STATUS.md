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

## C3 durable price catalogue — completed first slice

Recovered clean d516198. Scope: separate PostgreSQL billing schema for plans and
immutable scheduled GBP price versions, protected internal staff service and
minimal owner audit. Verify restricted database grants, exact money, effective
dates, preserved old IDs and transactional rollback. No payment integration.

Implemented migration 0004 and the internal staff catalogue. Separate plans and
append-only GBP versions use integer amounts, interval-specific effective instants,
trial length and API allowance. Historical versions remain readable by ID. The
catalogue stores verified actor attribution and projects minimal per-plan owner
audit from committed records. Restricted runtime and application permissions keep
customer/bearer/agent access separate. No pricing seed or billing route.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **9 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **76 passed**. Eight new pricing cases
  cover effective-date boundaries and persistence, preserved old IDs, duplicate
  rollback, audit permissions and attribution, separate database grants and rejected
  privileged connections. Historical Starlette test-client warning remains.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**
  because Chromium is unavailable for the unchanged browser lab test.
- `git diff --check`: passed.

Next: model tenant-scoped sandbox subscriptions that pin price versions and
validate trial/state changes before adding a verified provider event adapter.
Staff login, publication/retirement policy, retention, owner UI and entitlements
remain open. No provider connected, payments activated or deployment performed.
See `commercial/PRICING.md`. No active work remains in this increment.

## C3 tenant subscription sandbox — completed first slice

Recovered clean fb11bed. Scope: isolated PostgreSQL sandbox subscriptions with
pinned effective prices, trial deadlines, pending state for non-trial prices
and append-only cancellation. Verify tenant isolation and write permissions,
version preservation, trial boundaries and cancellation replay. No provider,
activation, customer billing route or live entitlement enforcement.

Migration 0005 adds a separately granted sandbox schema, forced RLS and
tenant-bound cancellations. An effective price is pinned at start, trial
expiry is calculated from the stored deadline, and cancellation is append-only
and repeatable. Pending and trial states cannot activate or charge a subscription.
One sandbox record per tenant prevents trial reset in this development contract.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **9 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **84 passed**. Eight sandbox
  cases cover pinned price/reconnect, exact expiry, cancellation replay,
  denied principals, dedicated grants and tenant-bound foreign keys. The first
  run had a test fixture Identifier attribute error; the corrected full run passed.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**
  at the unchanged Chromium-dependent browser lab test. No test skipped.
- `git diff --check`: passed.

Next: define authenticated and deduplicated sandbox provider-event handling
and reconciliation before connecting a provider. No real billing activation,
payments, subscription contract, live entitlement or deployment. See
commercial/SUBSCRIPTION_SANDBOX.md. No unfinished work in this increment.

## C3 simulated billing event receipts — completed

Recovered clean ca382d9. Scope: tenant-bound HMAC verification, short replay
window, PostgreSQL event deduplication and read-only subscription reconciliation.
No provider connection, transport, activation or payment state change.

Migration 0006 adds forced tenant RLS, a tenant-bound subscription reference
and unique event receipts. A tenant-configured simulator receiver verifies a
timestamped HMAC envelope, records price/state comparison metadata, replays
the original exact-body receipt and rejects changed-body reuse. The receiver
login cannot insert subscriptions or cancellations. No raw payloads stored.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **9 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **91 passed**. Seven new
  checks cover persisted replay, changed-body conflict, invalid signatures
  and timestamps, price/state mismatches, cross-tenant rejection, scoped
  receipts and separated database grants.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**
  at the unchanged browser lab test because Chromium is unavailable.
- `git diff --check`: passed.

Next: build an internal owner-only aggregate sandbox metrics service (trial,
pending, cancellation and event reconciliation counts). Do not include
customer documents or present simulated counts as live revenue. Provider
protocol, key rotation, webhook transport, live activation, quotas and
deployment remain separate. See commercial/SANDBOX_EVENTS.md.

## C3 owner sandbox metrics — completed

Recovered clean 39e57ea; no recorded unfinished increment, active writer, or
open PR for this branch. Scope: a fixed, cross-tenant PostgreSQL aggregate for
sandbox subscription states and simulator outcomes, exposed only to verified
interactive platform owners through a separate read-only database login. Verify
existing tenant isolation and that the metrics login cannot read source records.
No HTTP route, revenue measures, provider integration or activation.

Implemented migration 0007, a fixed aggregate view and a read-only internal
service. The view counts current sandbox subscription states and unique stored
receipt outcomes in one statement, with no tenant IDs or amounts. The separate
metrics login has no source schema access; existing sandbox runtimes retain
tenant isolation. The application additionally requires a separate interactive
platform-owner principal with MFA.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **9 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **96 passed**. Five new cases
  cover an empty snapshot, multi-tenant state and receipt counts, time cutoffs,
  role denials and database grants under a non-superuser migration owner.
  An initial assertion expected a permission error where PostgreSQL correctly
  rejected DELETE because the view is non-updatable; the corrected full run passed.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged browser test received 503. Chromium is installed in this
  environment, but its launch fails with a socket permission error; Playwright's
  alternate browser download also failed. No demo test skipped or changed.
- `git diff --check`: passed.

Next: qualify a maintained interactive staff identity adapter with verified MFA,
revocation and staff membership, before exposing owner functions over HTTP.
Keep tenant bearer identities separate. See commercial/SANDBOX_METRICS.md.
No provider, live billing, revenue reporting or deployment was enabled.

## C2 interactive staff identity boundary — completed first slice

Recovered clean 75d3fba with no recorded unfinished task or open branch PR.
Scope: verify a narrowly profiled staff OIDC callback ID token with PyJWT,
require recent provider-attested MFA, then resolve a separate PostgreSQL
staff membership with revocation. Exercise with fictional signed tokens and
least-privilege database grants. Browser callback, provider selection and
qualification, session issuance and owner HTTP routes remain outside this slice.

Migration 0008 adds a separate staff directory keyed by issuer and subject.
The PyJWT verifier checks the pinned staff client, signing key, login nonce
and provider-specific MFA assurance class and age. The database supplies the
role; revoked membership and authentications at or before its cutoff fail.
The dedicated lookup login cannot write memberships or access tenant data.
No new dependency version, provider connection or route was added.

Verification on 5 November 2026 (Python 3.12, PyJWT 2.13.0, psycopg 3.3.8):

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **15 passed**.
  Six new cases cover trusted signature/client/nonce, recent MFA and rejection
  of tenant bearer tokens by the staff verifier and staff ID tokens by the bearer verifier.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable PostgreSQL 16.2 via OMNIXAT_TEST_ADMIN_DSN: **101 passed**. Five new
  cases cover no self-enrolment, role changes, revocation, RLS and login grants.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged browser test returned 503; direct Chromium launch reproduced
  an operating system socket permission failure. No test skipped.
- `git diff --check`: passed.

Next: one-time login transaction storage and a bounded revocable staff session,
then maintained-provider qualification before adding any owner HTTP route.
See commercial/STAFF_IDENTITY.md for the trust boundary and exact limits.

## C2 one-time staff login transactions — completed

Recovered clean ac41562, with no unfinished task or open branch PR. Scope:
short-lived PostgreSQL login transactions bound to the initiating browser and
a fixed staff issuer/client/redirect URI. Generate nonce and S256 PKCE material
without storing raw state, browser credentials or PKCE verifiers; verify atomic
consumption under concurrent callbacks. No callback, session or provider wiring.

Migration 0009 adds an isolated five-minute login transaction store. The
database stores only derived keys and expiry. The service verifies the browser
binding and exact server configuration; it atomically consumes matching state
before returning the nonce and PKCE verifier to the trusted caller.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **15 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **109 passed**. Eight new cases
  cover cross-connection recovery, wrong binding/configuration, stored fields,
  expiry, concurrent callbacks, nested rollback, grants and insert failure.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium browser case returned 503; direct launch confirmed
  the environment denies its socket. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: a bounded revocable staff session with fresh role and MFA checks, then
qualify a specific provider's code flow with fictional accounts. Callback and
cookie wiring, rate limits and expiry pruning must precede exposing owner
HTTP routes. See commercial/STAFF_LOGIN.md.

## C2 revocable staff sessions — completed

Recovered clean 7932d45 with no unfinished increment or open branch PR.
Scope: a short-lived opaque PostgreSQL staff session issued after verified MFA,
with no raw token or cached role in storage. Recheck current staff membership
and MFA age on use and support explicit revocation. No web routes or provider.

Migration 0010 adds opaque staff sessions that expire five minutes from the
provider authentication time. The database stores a digest and identity
binding but no raw token or role. Resolution rechecks the live staff directory;
logout deletes one session. The directory and login-transaction database logins
stay separate from the session writer.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **15 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **117 passed**. Eight new cases cover
  verified issuance, digest storage, isolation, fresh role and revocation,
  cutoff, expiry, membership replacement and repeatable logout.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed the socket
  permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: qualify a specific identity provider with fictional accounts, then wire
the callback, cookies, CSRF, rate limits and expiry pruning before exposing
owner HTTP routes. See commercial/STAFF_SESSIONS.md. No deployment.

## C2 Keycloak staff code-flow adapter — completed first slice

Recovered clean c330b64 with no unfinished increment or open branch PR.
Scope: compose existing login transactions, ID-token verification and sessions
with a pinned Keycloak confidential-client code exchange. Verify issuer, PKCE,
bounded response handling and no credential forwarding on redirects. Use a
fictional HTTPS transport; do not provision a realm or expose staff routes.

Implemented a pinned Keycloak confidential-client adapter. It generates the
authorization URL and checks the callback issuer and browser binding before
exchanging a consumed code with S256 PKCE. Exchange responses are bounded,
redirects rejected, and only the ID token is passed to the existing MFA
verifier and session issuer. No dependency version, schema or route changed.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **15 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **120 passed**. Three new cases
  exercise the fictional exchange through real PostgreSQL, callback binding,
  PKCE and nonce verification, replay, redirects, malformed and oversized
  responses, upstream timeout and a streamed response that exceeds its deadline.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: run the fictional-account test matrix against an isolated Keycloak realm.
Then wire callback and cookies, CSRF, rate limits and expiry pruning before any
owner route. See commercial/KEYCLOAK_STAFF.md for setup and limits. No real
provider or deployment was enabled.

## C2 Keycloak realm preflight — completed

Recovered clean b4caaae with no unfinished increment or open branch PR.
The official Keycloak distribution download did not complete in this environment.
Scope: an offline, credential-free check of an isolated realm's exported OIDC
metadata and independently pinned RSA signing keys. No runtime discovery,
automatic trust changes, provider deployment or owner routes.

The preflight compares saved discovery metadata with exact pinned endpoints and
required code-flow capabilities, then validates independently approved RSA SPKI
fingerprints against public JWKS. The runtime adapter shares the endpoint
profile but does not fetch metadata or use the preflight to change key trust.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
  Six new cases cover pins and rotation, endpoint substitution, metadata
  capabilities, malformed or replaced keys, unsafe URLs and bounded CLI input.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **120 passed**.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

The official Keycloak release archive redirected to a download that timed out.
No realm was started or qualified. Next: run the preflight and fictional
browser MFA/recovery matrix in an environment with an isolated Keycloak realm
and working Chromium, then wire browser security controls before any owner
route. See commercial/KEYCLOAK_STAFF.md.

## C2 expired staff authentication cleanup — completed

Recovered clean f441918 with no unfinished increment or open branch PR.
Implement the independent expiry-pruning prerequisite: bounded PostgreSQL
cleanup of expired login attempts and staff sessions through a narrow
maintenance grant. Verify active rows survive, locked rows can be retried, and
operators receive counts only. No schedule, deployment or owner routes.

Migration 0011 adds a restricted operator function that deletes only expired
staff login attempts and sessions. It skips locked rows, caps each table at
500 deletions per call, and returns counts without requiring direct row access.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **124 passed**. Four new cases cover
  expired versus active rows, locked-row retry, SQL batch caps and role grants.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: run the isolated Keycloak browser MFA/recovery matrix, wire the callback
and cookie/CSRF/rate-limit controls, and configure a bounded maintenance runner
before exposing owner routes. See commercial/STAFF_AUTH_CLEANUP.md. No job or
realm was started and nothing was deployed.

## C2 staff browser qualification transport — completed

Recovered clean d3fdf70, with no unfinished increment or open branch PR.
Implement an explicitly constructed, separate ASGI qualification app for
staff login, callback, session check and logout, with exact origin and host
checks, strict callback parsing and secure cookies. Use fictional provider
responses; no owner routes, live realm, deployment or public listener.

The isolated ASGI factory now connects browser requests to staff login and
session services. It requires an exact HTTPS host and same-origin POSTs,
rejects ambiguous callback/cookie input, uses host-only secure cookies, and
requires an explicit admission hook. It adds no route to the customer app.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **130 passed**. Six new cases cover
  origin/host, admission failure, callback and cookie ambiguity, route
  separation, callback configuration and ASGI-to-PostgreSQL login/logout.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: run the browser MFA/recovery matrix against an isolated Keycloak realm,
including real cookie behavior; verify shared admission limits, access-log
redaction, request deadlines and the expiry runner before exposing owner
routes. See commercial/STAFF_BROWSER.md. No realm, listener or deployment.

## C2 shared staff browser admission limits — completed

Recovered clean 0c9ef73 with no unfinished increment or open branch PR.
Implement a shared PostgreSQL admission hook for the isolated browser app:
separate fixed-minute budgets by action and source, bounded state and a
dedicated execute-only role. Verify concurrent enforcement and no trust in
request forwarding headers. No listener, provider qualification or owner routes.

Migration 0012 and the optional admission hook enforce per-source and shared
budgets before staff authentication work. The database stores bounded keyed
counters, not raw IP addresses, and the admission role can only execute the
decision function. The hook ignores request forwarding headers and uses the
server-provided ASGI client address. No app is mounted automatically.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **136 passed**. Six new cases cover
  concurrent admissions, independent budgets, expiry and clock rollback, source
  normalization, grants and HTTP 429 before provider work.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed the socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: qualify the isolated Keycloak realm in a working browser and validate
trusted proxy addresses, log redaction, request deadlines and the expiry runner
before exposing owner routes. See commercial/STAFF_BROWSER.md. No deployment.

## C2 privacy-safe staff browser access events — completed

Recovered clean e4b3d76 with no unfinished increment or open branch PR.
Add a staff qualification access event that records only a fixed action label
and response status. Exercise success, denials and errors with fictional
credentials in request and response fields. Do not claim proxy, server or
identity-provider logs are covered, and do not deploy.

The staff browser qualification app now emits allowlisted action/status access
events. Unknown paths have a fixed label; request and response credentials,
client addresses and exception text do not enter the records. External access
logs are outside the app boundary and still need verification.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **139 passed**. Three new HTTP cases
  cover credential exclusion, error/rate-limit events and log sink failure.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: qualify the isolated Keycloak realm in a working browser and verify
ingress, ASGI and tracing log redaction with fictional canaries. Complete
request deadlines and the bounded expiry runner before any owner route.
See commercial/STAFF_BROWSER.md. No deployment.

## C2 bounded staff expiry runner — completed

Recovered clean b66db8f with no unfinished increment or open branch PR.
Add a one-shot operator command for the existing restricted expiry function.
Bound the number of independently committed batches and report counts only.
Verify the command with a real disposable database and maintenance login.
No scheduler, realm, staff route or deployment.

Added a one-shot cleanup command with fixed work caps, a statement timeout,
restricted-role checks and count-only JSON. It leaves active rows untouched
and can be retried after partial progress. No migration or schedule changed.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **142 passed**. Three new cases
  cover bounded batches, role isolation and real CLI output/error redaction.
  An initial schema-privilege error in the role inspection was corrected
  before the full suite passed.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: qualify the isolated Keycloak realm in a working browser, check ingress
log redaction and staff request deadlines, then configure and rehearse the
cleanup command in the qualification environment before owner routes.
See commercial/STAFF_AUTH_CLEANUP.md. No deployment or job activation.

## C2 staff request time budget — completed

Recovered clean 55358bd with no unfinished increment or open branch PR.
Add an isolated staff browser time budget across worker dispatch, admission,
connection acquisition and provider exchange. Reject late responses without
issuing browser credentials. Verify bounded-stage behavior with fictional
provider responses. No server, realm or owner route deployment.

The qualification app now shares a monotonic request budget with its
worker thread and pinned provider exchange. It checks admission and
connection acquisition, suppresses late success responses and limits
provider phases and session issuance to the remaining budget. This is
cooperative; synchronous calls already running are not cancelled.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **146 passed**. Four new cases
  cover late admission, late connection release, suppressed late cookies
  and no PostgreSQL session after a slow fictional exchange.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: run the isolated Keycloak MFA/recovery matrix in a working browser
and verify ingress deadlines, log redaction and maintenance cleanup in
that environment before owner routes. See commercial/STAFF_BROWSER.md.
No deployment.

## C4 PostgreSQL evidence registration — completed first slice

Recovered clean f27f4e3 with no unfinished increment or open branch PR.
While isolated Keycloak/browser qualification remains an environment gate,
implement the independent evidence intake foundation: tenant/organisation
scoped, append-only PostgreSQL document fingerprints with validated metadata
and safe concurrent duplicate registration. No file contents, upload route,
model calls, ledger writes or filing actions.

Migration 0013 and the internal evidence service add forced tenant isolation,
composite organisation binding and append-only fingerprint registration.
Concurrent exact duplicates return the original record; conflicting metadata
is rejected. Registration remains a trusted internal operation.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **32 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **152 passed**. Six new cases cover
  replay and attribution, metadata conflict, organisation and tenant scope,
  permission and input rejection, database grants/RLS and concurrent replay.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged Chromium case returned 503; direct launch confirmed a socket
  permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next for evidence: private staged object intake with streamed fingerprint and
size checks and a quarantine state before extraction. Staff owner routes still
require an isolated Keycloak/browser qualification run. See commercial/EVIDENCE.md.
No deployment, upload, model call, ledger effect or filing.

## C4 local evidence staging — completed

Recovered clean 055fe24 with no unfinished increment or open branch PR.
Implement a bounded, private temporary quarantine for evidence streams, with
computed SHA-256/size, cleanup on failure, and a scanner-facing byte reader.
Use fictional fixtures only. No HTTP route, durable storage, database
registration, scan result, extraction, ledger write or filing.

The internal POSIX spool now validates a declared media type and optional
length, enforces a 20 MiB ceiling, and hashes the original stream. A trusted
scanner can read the unnamed temporary file only within the staging context.
The file closes on all context exits. PostgreSQL metadata limits share the
same Python constants; the registry and staging stay independent.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **38 passed**.
  Six new tests cover short reads and exact bytes, size limits, malformed
  streams, private-directory checks, and cleanup after read/consumer failure.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **152 passed**.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. The unchanged Chromium case
  returned 503; a direct headless launch confirmed socket permission failure.
  No demo test changed or skipped.
- `git diff --check`: passed.

Next: implement tenant-scoped durable quarantine with immutable object identity,
retry and orphan cleanup. Bind a verified scan decision to the stored bytes
before extraction. Request deadlines, aggregate quotas and a qualified scanner
are still required. No upload route, real data or deployment.

## C4 durable PostgreSQL evidence quarantine — completed

Recovered the clean branch at 526ebe0. Add an internal bounded PostgreSQL
adapter that stores an original only against a matching tenant evidence
registration, with immutable bytes, metadata-only receipts and safe retries.
Keep bytes and receipt in one transaction so interrupted writes do not leave
separate storage objects. No scanner verdict, extraction, upload route or
deployment. Use fictional inputs only.

Migration 0014 stores the original and its receipt in one tenant-scoped row.
A composite foreign key binds PostgreSQL-computed digest and size to the
evidence registration. The internal adapter verifies organisation, media type
and original bytes, returns the existing receipt for matching concurrent
retries, and uses a role that cannot read or mutate stored payloads. No
external object is created, so interrupted writes leave no orphan blob.

Verification on 5 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **38 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **158 passed** after updating
  the upgrade test's migration count. Six new cases cover persistence, retries,
  tenant and organisation isolation, role grants, fingerprint enforcement and
  interrupted input.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. The unchanged demo browser case
  returned 503; direct Chromium launch confirmed socket permission failure.
  No demo test changed or skipped.
- `git diff --check`: passed.

Next: separate scanner role and a durable verdict tied to exact bytes and
scanner policy, then gate extraction on the verified decision. The adapter
buffers one bounded file; real use also needs capacity, retention, logging,
encryption and restore qualification. No deployment or real evidence used.

## C4 scanner verdict boundary — completed

Recovered clean cc1220a. Add a scanner-only service with an append-only
PostgreSQL verdict tied to the stored original and a configured policy
version. Verify separation from intake, failure handling and retry safety
with a fictional scanner. No real scanner, extraction, upload route or deployment.

Migration 0015 binds append-only scanner observations to the tenant,
quarantined bytes, digest, size and configured scanner policy. A separate
worker login reads the scoped original, verifies it, calls a trusted
scanner outside the database transaction and records only a supported
decision. Failures leave no decision; retries reuse the recorded observation.
If concurrent scans disagree, both outcomes survive and blocked takes
precedence on subsequent reads. No receipt authorises extraction.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **38 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **163 passed**. Five new cases
  cover exact bytes and policy binding, replay, failure, isolation/grants,
  and concurrent disagreement. A rerun caught a duplicate-index race in
  quarantine inserts after adding the foreign-key target; the insert now
  handles conflicts on both indexes and the final full run passed.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch confirmed
  socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: add a durable scan claim/recovery boundary, then enforce the active
policy, blocked precedence and exact byte binding before extraction.
A real scanner still needs isolation, time/resource limits and qualification.

## C4 durable scanner claims — completed

Recovered clean 14f8986. Add one expiring claim per tenant, quarantined
original and policy. Prevent simultaneous current workers, recover abandoned
claims, and reject stale completions before recording a verdict. Preserve
legacy verdicts and blocked precedence. No extraction or live scanner.

Migration 0016 adds database-timed scan claims with a 120-second lease.
Duplicate requests cannot invoke the scanner while a claim is live. An
expired claim can be reclaimed; completion checks the current lease token
and deadline, then atomically records the verdict and releases the claim.
Existing verdicts remain replayable, and blocked still wins for legacy
disagreements. An expired engine call may still be running; this is not
exactly-once execution or a scheduler.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **38 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **166 passed**. Scan cases
  cover a live claim, policy isolation, expiry without a replacement,
  takeover and stale rejection, plus legacy blocked precedence.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Chromium socket permission
  failure confirmed by direct launch. No demo test changed or skipped.
- `git diff --check`: passed.

Next: a separate extraction boundary that checks active policy, no live
claim, blocked precedence and exact byte binding. Scanner qualification,
engine timeouts and production recovery remain open. No deployment.

## C4 evidence extraction admission — completed

Recovered clean 70a4f20. Add an internal read boundary with a separate,
execute-only database role. Require a current configured policy, a clean
verdict on exact bytes, no blocked observation and no live claim. Test with
fictional evidence only; no parser, model, route or deployment.

Migration 0017 adds an operator-owned active policy and an execute-only
admission function. A read requires a clean observation on the exact
quarantined original, no blocked observation or live claim for the same
policy, and matching tenant and organisation. Empty configuration denies
admission. The worker adapter also recomputes the digest and checks size.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **38 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **169 passed**. Three new
  cases cover policy absence/change, exact original, blocked precedence,
  live claim, scope and execute-only privileges. The initial privilege
  inspection was corrected to require no USAGE on the raw evidence schema.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch confirmed
  socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: qualify a scanner and wire a bounded extraction worker with source
provenance, retry controls and an active-policy recheck before storing
results. The gate is a point-in-time read. No actual scanner, extraction,
route, live records or deployment.

## C4 source-linked CSV amounts — completed

Recovered clean 4962a43. Add a bounded deterministic CSV amount reader behind
the existing evidence gate. Use explicitly selected cells, preserve the
source reference and distinguish missing or ambiguous values from zero.
No result persistence, model, scanner activation or ledger effects.

The internal worker reads explicitly selected CSV cells after the existing
extraction gate. It preserves exact decimal amounts and binds each result
to an evidence ID, fingerprint, policy and source coordinates. Missing,
blank or ambiguous inputs produce no figure. Results are memory-only.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **170 passed**. The new
  integration case checks pre-scan and stale-policy denial and exact source binding.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch confirmed
  socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: durable, tenant-scoped extraction results with retry protection and
an active-policy recheck at write time. Scanner qualification, OCR,
model extraction, ledger effects and deployment remain outside this slice.

## C4 durable CSV extraction results — completed

Recovered clean f074a8a. Store bounded CSV results with source provenance,
tenant isolation and a stable job ID for retries. Recheck active policy
and source eligibility inside the write boundary. No public read API,
model, ledger effect or deployment.

Migration 0018 stores exact decimal strings and source coordinates with
the original fingerprint and scanner policy. An execute-only function
rechecks eligibility and holds the active policy through commit. An
identical retry reuses the original receipt; changed results conflict.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **174 passed**. Four new
  cases cover persisted provenance, same/changed and concurrent retries,
  scope, privilege boundaries, stale policy and policy rotation locking.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Chromium could not open a socket,
  confirmed by direct launch. No demo test changed or skipped.
- `git diff --check`: passed.

Next: a scoped review read service that rechecks current eligibility and
exposes unresolved cells for clarification. No public route, live scanner,
ledger effect or deployment.

## C4 scoped CSV review and clarification — completed

Recovered clean ad8119d. Add an internal read-only review service for
authorised tenant users. Recheck source eligibility and expose focused
clarification prompts for unresolved cells without exposing original bytes.
No public route, notifications, answers or ledger effects.

Migration 0019 adds an execute-only review read. A verified interactive
tenant user can review one currently eligible extraction; the separate
review login cannot read raw tables or call extraction functions. The
service validates stored candidates and prepares focused prompts only
for unresolved cells. It does not send questions or store answers.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **177 passed**. Three new
  tests cover unresolved questions and zero, stale policy, tenant and
  organisation scope, grants and rejection of malformed stored amounts.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: store authorised clarification answers linked to the exact job and
cell with a write-time eligibility recheck. No public route or deployment.

## C4 durable CSV clarification answers — completed

Recovered clean 0dc314d. Store one attributed answer per unresolved extraction
field and exact cell, with human write authority, repeatable retries and a
write-time eligibility recheck. Preserve the original candidate. No public
route, review overlay, ledger effects or deployment.

Migration 0020 stores separately attributed answers for an unresolved job
cell. The write gate rechecks source eligibility and holds the active
policy through commit. Identical retries return the first receipt; different
answers conflict. The source candidate remains unchanged.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **179 passed**. New cases cover
  zero versus unavailable, retries, wrong coordinates, human authorisation,
  role separation, tenant scope and stale policy.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch confirmed
  socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: show attributed answers in scoped review and suppress answered prompts
while preserving original values. No public route, ledger effect or deployment.

## C4 clarification answers in CSV review — completed

Recovered clean 13dcedb. Return attributed answers alongside original
candidates in scoped review and suppress only their matching prompts.
Preserve eligibility checks, role separation, and zero versus unavailable.
No ledger effects, routes or deployment.

Migration 0021 returns original candidates and separately attributed
answers in one eligible review read. Exact cell matches suppress prompts;
unavailable answers remain distinct from zero. Invalid stored answer
coordinates fail closed. Review and answer writer roles remain separate.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **180 passed**. Coverage
  includes answer provenance, zero/unavailable, prompt suppression,
  stale policy, role isolation and mismatched coordinates.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: a source-linked draft mapping for accounting preparation that refuses
unavailable or unanswered amounts and rechecks eligibility before writing.
No public route, ledger effect or deployment.

## C4 source-linked accounting draft amounts — completed

Recovered clean 94c6181. Persist a draft amount from one explicitly selected,
eligible CSV cell or its exact clarification answer. Refuse unavailable
values and recheck eligibility at write time. No currency inference, ledger
posting, routes or deployment.

Migration 0022 stores a draft amount and its source kind against the exact
job and cell. PostgreSQL derives the value, refuses unavailable or unanswered
cells, and holds the active policy through commit. Identical retries reuse
the receipt. No currency, date, account or tax treatment is inferred.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **182 passed**. New cases
  cover extracted and clarified amounts, scale, zero, exact cell matching,
  unanswered and unavailable cells, retries, scope, roles and stale policy.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: scoped draft read and validation of explicitly supplied accounting
context before creating expense or ledger drafts. No posting or deployment.

## C4 scoped accounting draft reads — completed

Recovered clean 8e5263c. Add a read-only service for one exact draft cell,
with source provenance and a fresh eligibility check. Keep reader grants
separate from writers. No accounting context inference or ledger effects.

Migration 0023 adds a dedicated read boundary for one exact draft amount.
It returns provenance with an exact decimal and withholds ineligible
results. Reader and writer database grants are separate.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **42 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **184 passed**. Two new
  cases cover exact decimal/provenance, policy rotation, scope and grants.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch confirmed
  socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: validate explicit currency, accounting date and account context for
expense or ledger drafts. No public route, posting or deployment.

## C4 explicit expense draft preflight — completed

Recovered clean 7be3020. Validate explicit GBP, accounting date and
expense account against a trusted tenant/organisation policy, then
prepare a preview from an eligible evidence draft without rounding.
No persistence, account provisioning, ledger posting or deployment.

The preflight accepts only explicit GBP, a date within the trusted
organisation period, and an eligible expense account. It checks source
eligibility and preserves provenance. Positive amounts convert to pence
without rounding. There is no database mutation.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **185 passed**. New coverage
  checks policy scope, dates, accounts, exact precision, eligible source and
  stale scanner policy.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No demo test changed or skipped.
- `git diff --check`: passed.

Next: persist tenant-scoped accounting periods and expense account policy
before implementing a transactional expense draft write. No posting or deployment.

## C4 persistent expense preparation policy — completed

Recovered clean c78beb8. Add operator-provisioned PostgreSQL accounting periods
and expense-account eligibility with tenant/organisation scope, then use the
selected period and account for a read-only evidence expense preview. Verify
default denial and role separation. No statutory rules, draft writes or posting.

Migration 0024 adds internal accounting periods and expense-account eligibility
with composite organisation references, forced tenant RLS and disabled defaults.
The separate execute-only preview reads policy and source eligibility in one
snapshot, preserving the selected period and exact source amount. Policy is
provisioned by a trusted operator; there is no chart of accounts or admin route.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **187 passed**. Covers
  missing/closed periods, disabled accounts, date bounds, exact scope,
  restricted grants, policy rotation and migration upgrade.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  confirmed a socket permission error. No demo test changed or skipped.
- `git diff --check`: passed.

Next: add a transactional, idempotent expense draft write that derives the
amount from eligible evidence and holds the selected accounting policy
through commit. No ledger posting, tax rules, routes or deployment.

## C4 transactional evidence expense drafts — completed

Recovered clean bac66a5. Save one GBP draft per exact source amount, with
server-derived pence, scope and provenance. Hold eligibility and selected
accounting policy through commit, and handle identical retries and conflicts.
No route, ledger posting or tax treatment.

Migration 0025 adds a separate execute-only expense draft writer. PostgreSQL
checks and locks the active scanner policy, quarantine/claim state, period and
account before deriving exact pence and saving one draft per extraction job
and amount field. Concurrent identical retries return one receipt; a changed
actor or context conflicts while the source and context are eligible. This is
not cross-job expense deduplication, an approval or a ledger effect.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **190 passed**, including
  concurrent replay, changed context, stale policy, permission boundaries,
  fractional pence, and held policy and scan locks.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: add a scoped expense draft read for review, with source provenance and
current eligibility. Keep payer, tax treatment and journal preparation separate.

## C4 scoped expense draft review — completed

Recovered clean c0dc046. Add an execute-only read of one expense draft by
tenant, organisation and receipt ID, returning provenance and rechecking
scanner and accounting policy. No listing, mutation, posting or approval.

Migration 0026 provides an interactive, read-only review of one scoped GBP
draft. It returns the saved context, attribution and exact source provenance
only if the evidence, period and account remain eligible and stored pence
matches the exact source. No document bytes or clarification text are returned.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **192 passed**. New cases
  cover receipt and provenance, tenant and organisation scope, reader grants,
  scanner rotation, closed periods, disabled accounts and amount integrity.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: record explicitly selected payer and funding context as a separate
draft-only step before preparing a balanced journal. No route or ledger posting.

## C4 explicit expense funding context — completed

Recovered clean 2d4121a. Record an explicit payer and funding source for
one eligible expense draft, from scoped operator configuration. Attribute
the choice and make identical retries safe. No payment, accounting
classification, journal, approval or posting.

Migration 0027 stores one attributed choice of payer and funding source per
draft. Operator-configured sources distinguish business from personal funds
and default to disabled. The execute-only writer rechecks draft eligibility
and locks the selected source. Identical eligible retries return one receipt;
a changed eligible selection or actor conflicts.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **194 passed**. New cases
  cover personal/business choices, concurrent replay, conflicts, payer mismatch,
  scope, disabled sources, stale evidence policy and role separation.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: make funding context available in scoped review and validate an
explicit eligible counterpart account before preparing a balanced journal.
There is no funding correction, payment verification or ledger action.

## C4 scoped expense funding review — completed

Recovered clean b648923. Read one attributed funding choice through a
dedicated read-only service. Distinguish an eligible draft with no recorded
choice from an unavailable draft, and show whether a recorded funding
source is still eligible. No account inference, correction or posting.

Migration 0028 adds an execute-only funding read. The service rechecks
expense eligibility and returns the saved choice and attribution with
current funding source status. It distinguishes an eligible draft without
a selection from an unavailable draft, and preserves disabled selections
for review without marking them eligible.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **196 passed**. New cases
  cover missing, enabled, disabled and unavailable choices; attribution;
  scope; policy changes; and read/write role separation.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: add tenant/organisation policy for an explicitly selected counterpart
account tied to the saved funding source before preparing a balanced journal.
No approval, posting or payment.

## C4 scoped counterpart policy and journal preview — completed

Recovered clean 93c4430. Add operator-configured counterpart eligibility
per tenant, organisation and funding source. Validate an explicit account
and prepare a balanced GBP preview from the currently eligible expense.
No persistence of journal lines, approval, payment or posting.

Migration 0029 adds an operator-managed, default-disabled counterpart
allowlist tied to the saved funding source. The execute-only preview
uses one read snapshot to validate evidence, expense, funding and
counterpart policy, returning two opposing lines in exact pence with
source provenance. It refuses the expense account as its own counterpart.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **198 passed**. New cases
  cover exact balance and provenance, missing funding, default-disabled
  policy, wrong source or scope, same-account rejection and role separation.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: persist a retry-safe, balanced journal draft and hold the relevant
eligibility checks through commit. No ledger posting or approval.

## C4 durable expense journal draft — completed

Recovered clean dbcbab5. Persist one balanced GBP journal draft per expense,
using the exact amount and explicit eligible counterpart. Lock eligibility
inputs through commit and return the same receipt on eligible retries.
No general ledger, approval, payment or posting.

Migration 0030 stores a balanced draft as one exact amount and two
distinct accounts, with source fingerprint, scanner policy and attribution.
The dedicated writer reuses preview eligibility after acquiring locks
on the relevant evidence and policy rows. Concurrent identical eligible
retries return one receipt; a different eligible selection or actor conflicts.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **200 passed**. New cases
  cover the saved snapshot, concurrent replay, conflicts, isolation, and
  attempts to change scanner, period, funding or counterpart policy before commit.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: add scoped journal draft review that compares the saved snapshot
with current eligibility and provenance. No posting or approval.

## C4 scoped saved journal review — completed

Recovered clean 799e653. Read one saved journal by tenant, organisation
and receipt ID. Return both lines and linked provenance only if the saved
snapshot still matches eligible inputs. No posting, approval or mutation.

Migration 0031 adds an execute-only journal draft reader. It compares the
saved snapshot to currently eligible inputs and returns the original
receipt, attribution, exact lines and linked source provenance. Missing,
out-of-scope, stale and mismatched drafts are unavailable. No changes are
made to saved drafts, approvals or ledger balances.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **202 passed**. New cases
  cover exact lines and provenance, scoped reader grants, scanner rotation,
  disabled counterpart policy and mismatched saved amount or fingerprint.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: design an attributed human review decision bound to the exact
eligible journal snapshot, separate from any statutory approval or posting.

## C4 human journal review decisions — completed

Recovered clean 3dfc0ee. Bind an attributed human bookkeeping review
decision to the exact currently eligible journal snapshot. Keep retries
safe and deny agents and API keys. No posting or statutory approval.

Migration 0032 returns a versioned snapshot digest in journal review and
records an attributed `reviewed` or `changes_requested` observation only
when the supplied digest matches the eligible snapshot at the write check.
Same-reviewer identical retries return the receipt; a changed decision
conflicts. The record is historical and conveys no authority or readiness.
The journal reader grant must be replaced as documented in EVIDENCE.md.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **204 passed**. New cases
  cover attributed decisions, concurrent replay, conflicting decisions,
  timezone-stable digests, stale inputs, scope and read/write role separation.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: expose scoped review observations for the exact current snapshot,
keeping historical decisions distinct from any posting or filing approval.

## C4 scoped journal decision history — completed

Recovered clean 981097c. Expose bounded, attributed observations for the
exact currently eligible snapshot through a separate read-only grant.
Keep empty history distinct from stale or unavailable snapshots and do
not derive approval, posting or readiness from observations.

Migration 0033 adds a dedicated execute-only read of decisions for one
eligible journal snapshot. Reviewers, decisions and timestamps are
paginated by reviewer ID. A stale digest cannot continue a page, and
historical decisions remain stored but separate. No aggregate verdict.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **206 passed**. New cases
  cover attributed pagination, empty pages, exclusion of older snapshots,
  stale cursor rejection, eligibility, scope and role separation.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: attach a structured correction request to an exact changes-requested
observation, without mutating the saved journal or granting approval.

## C4 structured journal correction requests — completed

Recovered clean 89f1222. Allow an interactive reviewer to attach one
structured correction reason to their own changes-requested observation
for the exact eligible snapshot. Keep the saved journal and observation
unchanged; no free text, posting or approval.

Migration 0034 stores one fixed-category reason on the reviewer's own
changes-requested observation for an eligible journal snapshot. The
database enforces the scoped parent and decision type. Identical eligible
retries reuse the receipt; conflicting reasons are rejected. The draft
and observation remain unchanged.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **208 passed**. New cases
  cover concurrent replay, conflicts, exact snapshot binding, the parent
  decision constraint, stale policy, tenant scope and restricted grants.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: show correction reasons alongside the corresponding current-snapshot
observations through a scoped read. No correction resolution or posting.

## C4 journal correction history — completed

Recovered clean 22eca98. Return structured correction reasons and timestamps
on the same bounded, scoped read as their current-snapshot observations.
Keep decision receipts and cursor behavior unchanged. No resolution or posting.

Migration 0035 adds structured correction receipts to the same scoped
snapshot and page as their parent decisions. No older snapshot or
lookahead-row correction is returned. Existing decision receipts are
unchanged; replace the decision reader grant as described in EVIDENCE.md.

Verification on 6 November 2026, Python 3.12 / disposable PostgreSQL 16.2:

- `cd commercial && python3 -m unittest discover -s tests`: **44 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **208 passed**. Extended
  cases cover exact correction receipts, lookahead exclusion, historical
  corrections for the same reviewer, stale cursors and denied table reads.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct launch confirmed
  Chromium socket permission failure. No prototype test changed or skipped.
- `git diff --check`: passed.

Next: derive focused follow-up prompts from current-snapshot correction
reasons without guessing values or changing the journal. No posting.

## C4 journal correction questions — implemented

Recovered clean 413f0cf. Derive fixed, focused questions from the correction
reasons returned on each exact-snapshot decision page. Keep the read scoped
and deduplicate reasons within each page. The questions introduce no guessed
values and leave journal and review records untouched.


The scoped decision page derives one question per distinct reason in order
of first appearance. The questions ask for the missing detail and supporting
context without incorporating record values. Deduplication across pages
belongs to callers collecting questions for the same snapshot.

Verification on 6 November 2026, Python 3.12:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
  New tests cover all five reasons, deduplication, order and empty input.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`:
  **16 test module import errors** because psycopg is unavailable. The
  package download was blocked by the runner's network policy. The
  extended PostgreSQL paging test is pending in an equipped environment.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced a socket permission failure. No prototype test changed.
- `git diff --check`: passed.

Next: rerun PostgreSQL integration tests, then record explicit clarification
answers against the exact eligible snapshot and reason. Keep journal changes
and any approval as separate actions.

## C4 journal clarification answers — completed

Recovered clean `1ff6e87`. Add an internal write for one attributed, bounded
answer per correction reason on an eligible journal snapshot. Reference an
actual correction request, preserve original observations and reject conflicting
retries. Add no posting, approval or external transport.

Migration 0036 and the internal service record one attributed answer per
eligible snapshot and reason. A composite foreign key binds the answer to
an actual correction. Identical retries by the same author reuse the first
receipt, including when another reviewer requested the same reason.
The receipt excludes answer text. No journal or review record is edited.

Verification on 6 November 2026, Python 3.12 and disposable PostgreSQL 16.2
built from the checksum-verified upstream release, with the pure-Python
psycopg adapter from the repository's pinned 3.3.8 upstream tag:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **210 passed**, including
  the previously pending correction-question paging coverage. New cases
  exercise concurrent retries, duplicate reasons, conflicts, cross-tenant
  rejection, stale policy, human-editor authorization and dedicated grants.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: return attributed answers through the scoped journal decision read
and suppress questions already answered for the eligible snapshot and reason.

## C4 scoped journal clarification review — completed

Recovered clean `4150bed`. Return attributed answers only for correction
reasons on the current eligible decision page. Suppress answered questions
across reviewers of the same snapshot while keeping the existing cursor.

Migration 0037 returns attributed answers for correction reasons on the
eligible decision page. Duplicate reasons share the same answer even
across reviewers on different pages. Historical and lookahead answers
are excluded. Existing cursors and observation receipts are preserved.
Replace the dedicated decision reader grant as documented in EVIDENCE.md.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **211 passed**.
  Coverage includes historical and off-page answers, same-reason deduplication,
  stale snapshots, reader permissions and direct table access denial.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Chromium failed to create
  a socket on direct launch. The browser test is unchanged.
- `git diff --check`: passed.

Next: let an authorised user link eligible evidence to an answered
correction for later review. Keep answer text separate from verified
evidence and leave journal edits and posting to separate actions.

## C4 journal clarification evidence links — completed

Recovered clean `a5baae9`. Let an authorised human editor link one eligible
supporting original to an answered reason on the exact journal snapshot.
Persist the scoped evidence fingerprint and scan policy with attribution.
Keep journal data, answer text and bookkeeping decisions separate.

Migration 0038 stores one supporting original per answered reason and
snapshot, with scoped foreign keys to the answer and evidence fingerprint.
The writer rechecks the current journal and original's eligibility and
holds the active scan policy and supporting original scan state through
commit. Concurrent identical retries return the first receipt. The
receipt contains no evidence bytes or answer text.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **213 passed**. New tests
  cover concurrent replay, conflicting actor or evidence, stale snapshots,
  missing answers, blocked or unscanned evidence, organisation and tenant
  isolation, policy changes and restricted grants.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: show supporting evidence references in the scoped decision page,
with current eligibility and no original bytes. Keep historical links
separate from any later correction or posting decision.

## C4 journal supporting evidence review — completed

Recovered clean `68e7997`. Return the attributed supporting evidence reference
alongside its clarification answer, restricted to the eligible journal snapshot
and visible reasons. Recheck the linked fingerprint against the current scan
gate and keep historical attribution even when the link is no longer eligible.

Migration 0039 returns supporting evidence metadata beside its answer.
It distinguishes missing links from links whose exact fingerprint is no
longer eligible and leaves original bytes behind the scan gate. Replace
the dedicated decision reader grant as documented in EVIDENCE.md.
Migration 0040 fixes concurrent replay collisions across the overlapping
unique indexes used by the decision, correction and answer writers.
Applied migration files, scoped foreign keys and grants are preserved.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **213 passed** after
  correcting the pre-existing duplicate-index retry errors. Coverage
  includes current and blocked links, lookahead exclusion and denied
  access to original bytes from the decision reader.
- Ran the existing concurrent decision, correction and answer test methods
  20 times each in a single unittest suite: **60 passed**.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: preview an amount correction from an explicitly selected verified
CSV amount in linked supporting evidence. Keep the original journal and
answer intact and leave posting to a separate action.

## C4 journal amount correction preview — completed

Recovered clean `31818ca`. Add a read-only preview from an explicitly selected
CSV extraction cell on the evidence linked to an answered amount correction.
Require explicit GBP confirmation, current scan eligibility and exact pence.
Preserve the journal, clarification and ledger records.

Migration 0041 provides a scoped read from the answered amount correction
to its linked original and explicitly selected, eligible CSV extraction
cell. The service requires GBP and a positive whole-pence result. It
returns the original pence amount, both balanced proposed lines and
source provenance. The preview is read-only.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **215 passed**. The new
  tests cover exact pence, balanced accounts, source provenance, isolation,
  blocked originals, mismatched jobs and cells, role separation and
  preservation of the original journal.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: persist an attributed amount-correction proposal against the original
snapshot with a retry-safe receipt and current source revalidation. Journal
replacement and ledger posting remain separate decisions.

## C4 durable journal amount correction proposals — completed

Recovered clean `88124f2`. Save one attributed amount-correction proposal
per exact journal snapshot, derived from the linked extraction cell.
Revalidate source and journal eligibility and protect it through commit.
Keep original journals and ledger balances separate from proposal storage.

Migration 0042 saves one source-derived, attributed proposal per exact
journal snapshot. It records original and proposed pence, both account IDs,
evidence fingerprint and the exact extraction cell. Current journal and
source eligibility is protected through commit. Identical eligible retries
return the first receipt; different author or source inputs conflict.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **218 passed**. New
  coverage includes concurrent replay, conflicting sources and authors,
  permission and tenant boundaries, rollback, invalid amounts, and locks
  protecting journal policy, both originals and extraction through commit.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: read a saved proposal by receipt ID, compare it with the exact current
journal and source and return its attributed balanced lines for review.

## C4 saved amount-correction proposal review — completed

Recovered clean `cb475dc`. Read one saved proposal by receipt ID with tenant
and organisation scope. Recheck the exact journal snapshot and selected CSV
source before returning attribution, original pence and both proposed lines.

Migration 0043 returns one attributed saved proposal only when its original
journal snapshot and exact selected source still match. The read compares
fingerprint, scan policy, original and proposed pence and both account IDs.
It reuses the preview's typed balanced-line representation.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **220 passed**.
  New cases cover exact receipts and attribution after reconnect, tenant
  and organisation scope, changed proposal fields, stale journal inputs,
  blocked supporting evidence and dedicated read grants.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: record an attributed human bookkeeping review decision bound to the
exact saved proposal. Keep journal replacement and posting separate.

## C4 exact-proposal human review decisions — completed

Recovered clean `d3fa61e`. Add a versioned digest of the exact eligible
saved proposal and record attributed human bookkeeping observations against
it. Preserve historical decisions and provide retry protection.

Migration 0044 exposes a versioned digest of the eligible saved proposal
and records one attributed bookkeeping observation per reviewer and digest.
Identical eligible retries return the original receipt; different decisions
conflict. A changed proposal requires its new digest and retains historical
decisions. Replace the saved-proposal reader grant as documented in EVIDENCE.md.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **222 passed**.
  Coverage includes concurrent decision replay, conflicts, stale digests,
  changed attribution, historical decisions, timezone-independent hashes,
  tenant scope, nonhuman rejection and restricted grants.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: return a bounded, scoped history of review decisions for the exact
eligible proposal digest. Journal replacement and posting remain separate.

## C4 correction proposal decision history — completed

Recovered clean `2d8d12f`. Return a bounded page of attributed decisions
for the exact eligible proposal digest. Preserve reviewer ordering and
exclude observations against older digests or other tenant scopes.

Migration 0045 returns a bounded page of attributed decisions for the
exact eligible proposal digest. Cursor ordering is by reviewer ID and
stale digests fail closed. Empty eligible pages remain distinguishable
from unavailable proposals. Older observations remain stored separately.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **224 passed**.
  New cases cover paging and empty pages, history exclusion, stale cursors,
  scope, malformed pagination, restricted grants and blocked source evidence.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: preview an explicit replacement journal draft linked to the exact
proposal and an attributed reviewed observation. Preserve the original
journal and keep posting as a separate operation.

## C4 reviewed replacement journal preview — completed

Recovered clean `671b6ed`. Preview a replacement draft using the exact
eligible correction proposal and an explicitly selected reviewed observation.
Retain the original journal's accounting context and source-linked balanced
amounts. Keep this operation read-only.

Migration 0046 returns a replacement preview tied to an explicitly
selected reviewed observation on the exact eligible proposal digest.
It carries the original journal's accounting date, period and funding
source with the proposal's balanced amounts and evidence provenance.
The operation is read-only and returns the selected observation's author
and timestamp.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **226 passed**.
  New cases cover exact review attribution, preserved accounting context,
  stale/missing/changes-requested observations, tenant scope, source
  blocking, restricted grants and unchanged original journals.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: save a retry-safe replacement draft linked to the exact proposal,
selected reviewed observation and original journal. Preserve the original
and hold current eligibility through commit.

## C4 durable linked replacement drafts — completed

Recovered clean `8309afd`. Save one attributed replacement draft per
original journal, bound to the exact proposal and selected reviewed
observation. Reuse transactional proposal revalidation to hold current
journal and source eligibility through commit. Preserve original records.

Migration 0047 saves one linked replacement draft per original journal.
Its snapshot includes exact proposal and reviewed-observation references,
original accounting context, both balanced account amounts and source
provenance. The writer reuses proposal replay to hold current journal and
source eligibility through commit, and locks the selected observation.
Identical eligible retries return the original receipt.

Verification on 7 November 2026, Python 3.12 and disposable PostgreSQL 16.2
with the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **229 passed**.
  New tests cover exact persisted attribution/provenance, concurrent replay,
  author conflicts, stale or missing reviews, permission boundaries,
  original-record preservation, rollback and commit-time eligibility locks.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch
  reproduced the socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

Next: read one saved replacement draft by receipt ID, revalidate the
original snapshot, proposal, selected review and source, and return its
attributed balanced lines.

## C4 saved replacement draft review — complete

Recovered clean `6cddd28`. Read a saved replacement by receipt ID with tenant
and organisation scope. Compare the saved snapshot with the exact current
proposal, selected reviewed observation, original journal and source before
returning attribution and balanced lines.


Migration 0048 and the shared Python reader return a saved replacement receipt,
author and typed balanced preview through a dedicated read-only database role.
The read checks tenant and organisation scope, the exact original snapshot,
proposal digest, selected reviewed observation, accounting context and current
source eligibility on one statement snapshot.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **231 passed**.
  Added coverage for saved attribution and balanced preview, fresh connections,
  wrong scope, role boundaries, changed accounting/provenance fields, changed
  review observations, blocked evidence and changed original snapshots.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch again
  failed with a socket permission error. The browser test is unchanged.
- `git diff --check`: passed.

This increment provides saved-draft review. Production web/API integration,
identity-provider provisioning and final-package human approval remain open.
Next: design and implement an explicit, retry-safe choice of the current
replacement draft while preserving original lineage and review history.

## C4 explicit replacement selection — completed

Recovered clean `4d776d5` with no active task or competing writer found.
Add an attributed, retry-safe selection of one saved replacement for its
original journal and exact proposal digest. Reuse existing write-time
eligibility locks, preserve all originals and review records, and return
an immutable selection receipt. This is a draft preparation choice.


Migration 0049 and the shared Python selection service persist one attributed
choice per original journal with exact original/proposal digests. Composite
references and forced RLS preserve tenant, organisation and original lineage.
Existing replacement replay holds source, policy, journal and review eligibility
through commit. The saved replacement is also locked and rechecked. Identical
eligible retries return the original receipt and competing attribution conflicts.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **234 passed**.
  Added coverage for concurrent replay, exact selection attribution, preservation
  of originals, database access boundaries, composite lineage, wrong scope and
  digest, stale or changed sources, commit-time locks and rollback.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch reproduced
  the socket permission error. The browser test remains unchanged.
- `git diff --check`: passed.

This is a durable draft preparation choice. The receipt remains historical when
eligibility changes. Production transport, ledger posting and final-package
approval remain separate unfinished work.
Next: add a unified current-draft reader that resolves the selected replacement,
rechecks its exact snapshot and current eligibility, and preserves lineage.

## C4 unified current journal draft reader — completed

Recovered clean `5a7d2ee` with no unfinished task or competing writer found.
Read the original or explicitly selected replacement on one statement snapshot,
revalidating current evidence, review and exact selection digests. Return typed
balanced journal lines with original lineage and selection attribution. An
ineligible selected replacement makes the current read unavailable.


Migration 0050 and the shared Python reader resolve original and selected
replacement data on one statement snapshot. The typed result preserves the
original review, replacement review and exact attributed selection. Its `journal`
property supplies the effective balanced lines with the selected source's exact
fingerprint, extraction job and cell. Saved replacements require an explicit
selection. Stale or ineligible selections make the current read unavailable.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **237 passed**.
  Added coverage for original-only records, saved but unselected replacements,
  explicit selections, balanced amounts, exact provenance, separate attribution,
  original preservation, reconnects, scope/role boundaries, corrupt selection
  digests, changed observations, blocked sources and changed original snapshots.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch reproduced
  the socket permission error. The browser test remains unchanged.
- `git diff --check`: passed.

The service is internal and read-only. Production transport, maintained-provider
qualification, ledger posting and final-package approval remain unfinished.
Next: resume the production-target PostgreSQL job persistence work recorded in
the durable-job update. Reuse the existing SQLite contract for tenant-scoped
creation, idempotent replay and recoverable worker checkpoints before connecting
the shared evidence/journal services to autonomous orchestration.

## C1 PostgreSQL agent-job persistence — completed first slice

Recovered clean `305b050` with no active task or competing writer found.
Implement the existing create/read/claim/checkpoint interface over tenant-scoped
PostgreSQL transactions, with concurrent idempotency, database-timed leases,
worker-bound fencing and restart-safe progress. Preserve the SQLite development
adapter. Ledger effects and autonomous orchestration remain subsequent work.


Migration 0051 and `PostgresJobStore` provide tenant-scoped create/read/claim/
checkpoint operations through the shared PostgreSQL transaction boundary. The
schema forces RLS and validates queued/running/completed state and bounded JSON
progress. Creation stores the payload hash and original actor with concurrent
idempotency. Claims and progress use the database clock after row-lock acquisition.
The current worker identity and token must match, and completion clears the lease.
The worker-identity check is an additional restriction in this PostgreSQL adapter.
See JOBS_POSTGRES.md for the dedicated role grants, interface and trust boundary.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **247 passed**.
  Ten new tests cover reconnect/recovery, creator attribution, same/different
  payload races, single-winner claims, expiry/reclaim, worker/token fencing,
  lock-wait expiry, tenant RLS, scope/role safety, validation, database state
  constraints and rollback after a rejected JSON checkpoint.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch reproduced
  the socket permission error. The browser test remains unchanged.
- `git diff --check`: passed.

This internal adapter uses server-verified Principals and an exclusive connection
per operation. Current membership/revocation must be resolved by callers. Runtime
SQL privileges trust the application boundary. Production operational qualification,
worker scheduling, cancellation, retry budgets and atomic ledger-effect handling
remain unfinished. SQLite retains its separate development contract.
Next: add tenant-authorised PostgreSQL job cancellation and reject further claims
or checkpoints after cancellation, then qualify operation-specific effect
idempotency before connecting autonomous orchestration.

## C1 PostgreSQL job cancellation — completed

Recovered clean `25ead85` with no active task or competing writer found.
Add tenant-authorised cancellation using the existing records-write boundary.
Persist the first cancellation attribution and time, clear active leases and
preserve checkpoints. Serialize cancellation against claims and completion.


Migration 0052 adds the cancelled state and database-enforced cancellation
attribution. `PostgresJobStore.cancel` uses existing tenant records-write checks,
locks the job, stores the first actor and database timestamp, preserves progress
and clears the lease. Retries return the first receipt. Claims, checkpoints and
completion serialize against cancellation. Completed jobs retain their terminal
state. Authorised agent and scoped API writers follow the same permission boundary.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **255 passed**.
  Eight new tests cover queued/running cancellation, receipt replay/reconnect,
  concurrent cancel/claim/complete outcomes, scope and role boundaries, terminal
  state constraints, transaction rollback and upgrade of existing queued, running
  and completed jobs with repeatable checksum-verified migrations.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch reproduced
  the socket permission error. The browser test remains unchanged.
- `git diff --check`: passed.

Cancellation governs preparation state. In-flight external work, committed domain
effects, current membership verification and transport wiring need their separate
controls. Next: introduce a fenced transaction boundary for one idempotent
preparation effect, with a durable operation receipt and job authority checked
under the same transaction before autonomous orchestration.

## C1 fenced job note preparation — completed

Recovered clean `eb57a00` with no unfinished task or competing writer found.
Create one organisation note through the existing validated record repository,
with a job-scoped operation receipt in the same transaction. Lock and recheck
worker/token/lease authority, preserve actor attribution across recovered retries,
and roll back the note, record audit and effect receipt together on failure.


Migration 0053 and `PostgresJobStore.create_note_effect` create organisation notes
through the existing record repository with a job-scoped receipt in the same
transaction. Job state, current worker, token and lease are checked under the job
lock before and after preparation. Concurrent retries and recovered workers reuse
the original note and actor. Changed inputs or a changed saved note conflict.
Cancellation serializes against note creation. All participating tables have
forced tenant RLS and runtime ownership checks. See JOBS_POSTGRES.md for grants.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **262 passed**.
  Seven new tests cover receipt replay after reconnect/reclaim, concurrent retries,
  exact note/audit attribution, changed inputs and notes, foreign/missing parents,
  permissions and job authority, cancellation races, atomic rollback and expiry
  after creating the note but before committing its effect receipt.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch reproduced
  the socket permission error. The browser test remains unchanged.
- `git diff --check`: passed.

This increment covers a local note preparation effect. Current identity resolution,
ledger posting, external effects and worker orchestration remain unfinished.
Next: persist bounded job retry/failure outcomes and attempt budgets so recovered
or failing preparation can stop predictably before adding an autonomous worker.

## C1 bounded job attempts and failure outcomes — completed

Recovered clean `44fc84c` with no active task or competing writer found.
Persist immutable creation-time attempt limits, counted claims, delayed retry
eligibility and fixed-code failure receipts. Serialize failure/retry with existing
job authority, cancellation and completion. Preserve legacy job data and document
that migration starts a fresh counted-attempt budget for existing jobs.


Migration 0054 persists a pinned attempt limit, counted claims, retry eligibility
and fixed-code failure receipts. The default limit is 3 and creation can configure
1–20. Delayed retries require database-clock eligibility and remaining budget.
Exhausted expired claims become terminal failed state. Explicit failure and its
receipt commit together under worker/token checks. Replaying an old receipt
preserves a newer claim. Cancellation, completion and failure serialize together.
The existing get response shape is retained, with separate retry_state metadata.

Existing jobs receive a new counted-attempt budget starting at migration time.
Earlier totals were never stored. Their original state/progress/leases are retained,
and claims acquired after migration consume the new count. See JOBS_POSTGRES.md
for full semantics and the additional SELECT, INSERT failure-receipt grant.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **269 passed**.
  Seven new tests cover pinned limits, delayed retries, exhausted leases, repeated
  failure receipts, newer-claim preservation, scope/validation, commit rollback,
  competing terminal transitions and delayed-retry cancellation. The existing
  upgrade case also verifies preservation of prior fields and new budget defaults.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. Direct Chromium launch reproduced
  the socket permission error. The browser test remains unchanged.
- `git diff --check`: passed.

Current identity resolution, provider execution and autonomous workers remain
unfinished. Job creation currently stores a payload hash. Next: persist validated,
tenant/organisation-bound, reference-only preparation task inputs so a restarted
worker can recover its specification before adding orchestration.

## C1 recoverable evidence task specifications — completed

Recovered clean `2e8fd3d`; no unfinished task or competing writer found.
Persist version-1 reference-only evidence preparation specifications with exact
organisation/evidence/fingerprint binding, atomic job creation and immutable retry
inputs. Preserve hash-only legacy jobs without inventing recoverable inputs.
Task recovery does not release document bytes or bypass the existing scan gate.


Migration 0055 and `EvidencePreparationTask` persist one version-1 reference-only
specification per new typed job. Exact tenant/organisation/evidence/fingerprint
foreign keys retain source binding. Creation and specification commit atomically;
concurrent replay preserves original attribution and pinned attempt limits.
`get_evidence_task` recovers immutable inputs after reconnect/reclaim. Existing
hash-only jobs remain unchanged and cannot acquire invented specifications.
See JOBS_POSTGRES.md for grants, retention dependencies and execution boundaries.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests -q`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **276 passed**.
  Seven new tests cover exact-input recovery, concurrent replay, changed limits
  and references, wrong tenant/organisation/fingerprint, permissions, legacy
  behaviour, atomic rollback, schema constraints and immutable runtime grants.
  The existing upgrade test also checks that migration invents no task inputs.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed** with Chromium unavailable. The
  unchanged browser test returns 503; no test was skipped or removed.
- `git diff --check`: passed.

Task recovery returns references only. It does not bypass the current scan/read
gate or grant execution authority. No provider, autonomous worker or UI is wired.
Next: a bounded preparation executor using recovered inputs, fresh membership,
worker/lease checks and the existing evidence gate, with restart-safe domain effects.
Ledger posting, external providers and production qualification remain unfinished.

## C1 authenticated preparation job boundary — completed

Recovered clean `ae98077`; no active implementation or competing writer found.
Connect the existing signed access-token verifier and persisted membership checks
to typed job creation, recovery, claims, progress, failure, cancellation and note
effects. Resolve current authority for every call without caching principals or
retaining bearer tokens. Preserve the records identity behaviour and job fencing.
This is the identity prerequisite for a bounded executor; no scheduler starts.


`AuthenticatedJobStore` resolves a fresh signed-token identity and persisted tenant
membership before each existing typed job operation. The shared lookup also backs
`authenticated_records`, retaining its single-transaction behaviour. Separate
minimal identity/job connections keep identity tables outside the job login.
The boundary caches no principals or bearer tokens and accepts no role headers.
Existing job attribution, retry receipts, cancellation and worker fencing remain
in the shared store. No migration is needed. See JOBS_POSTGRES.md for grants and
per-call revocation semantics.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests -q`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **285 passed**.
  Nine new tests cover signed-agent lifecycle and recovery, original effect
  attribution, all-method revocation, role downgrades, invalid/expired tokens,
  identity cutoff/disablement, scopes, tenant isolation, worker identity fencing,
  least-privilege connections and current authority on terminal receipt replay.
  Existing authenticated record/HTTP behaviour remains covered by the full suite.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. The unchanged browser test receives
  503 with Chromium unavailable. No test was skipped or removed.
- `git diff --check`: passed.

Identity lookup and job work are separate transactions. Revocation governs the
next lookup, not an admitted call or effects already committed; token expiry is
checked at entry. This is the identity prerequisite for a bounded executor, not
an executor or production-qualified identity integration. Next: connect recovered
task inputs to the current evidence gate under a live worker lease, and execute
one bounded restart-safe preparation step. Scheduling, external providers, ledger
posting and final-package approval remain unfinished.

## C1 bounded evidence inspection step — completed

Recovered clean `192d6a5`; no unfinished implementation or competing writer found.
Inspect one recoverable task through the current scan/read gate after checking its
verified worker and live lease. Compare the exact source fingerprint, retain only
metadata in progress and recheck identity/lease before saving. Add a conditional
checkpoint to prevent this step overwriting newer progress. No provider, ledger,
filing, scheduler or UI is activated.


`inspect_preparation_evidence` now runs one explicit bounded inspection using the
immutable task, fresh signed identity and the existing current-policy evidence
read gate. `get_claimed_evidence_task` reads the exact task/progress together only
for a live verified worker. Inspection checks the pinned evidence ID/fingerprint
and returns/saves only metadata. Conditional `expected_progress` checkpoints
prevent stale inspection from overwriting newer preparation; existing callers
retain their unconditional checkpoint behaviour. The job stays running.
No migration is required. See JOBS_POSTGRES.md for roles and snapshot limits.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests -q`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **294 passed**.
  Nine new tests cover metadata-only recovery/retry, initial claim/scope checks,
  disabled or changed scan policies, blocked verdicts/live scan claims, exact
  fingerprint matching, cancellation/expiry/reclaim during read, fresh authority
  before checkpoint, newer-stage preservation and concurrent conditional writes.
  Existing revocation, role-downgrade and wrong-worker cases include claimed reads.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**. The unchanged browser test receives
  503 with Chromium unavailable. No test was skipped or removed.
- `git diff --check`: passed.

The checkpoint records an inspection observation, not continuing evidence
eligibility or completed processing. Transactions remain separate; checks cannot
retract bytes already admitted into trusted memory, and later effects must recheck
the current gate/authority. No original bytes leave this step and no external work
is executed. Next: persist a validated source-specific extraction plan and connect
the existing bounded decimal extraction service to a fenced retry-safe job effect.
Scheduling, providers, ledger posting, final approval and production qualification
remain unfinished.

## C1 saved CSV extraction plans — completed

Recovered clean `b5451f0`; no unfinished implementation or competing writer found.
Persist one immutable, validated, bounded CSV cell-selection plan per exact evidence
task. Save/replay under fresh identity and live worker lease, preserve first actor,
reject changed inputs and retain plans for restart recovery. Reuse the existing CSV
selection validation. This increment prepares durable inputs; execution remains next.


Migration 0056 stores one immutable versioned plan per exact evidence task with
forced RLS, task foreign keys and an ordered canonical digest. `save_csv_plan`
checks fresh authority and current worker/lease, locks the job, serializes retry
and cancellation, preserves first attribution and rolls back on expiry/failure.
`get_csv_plan` validates/digest-checks inputs after restart. Shared coordinate
validation keeps the existing CSV extractor and saved plan contract aligned.
Apply the additional SELECT, INSERT plan grant in JOBS_POSTGRES.md.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2
and the pinned psycopg 3.3.8 source adapter:

- `cd commercial && python3 -m unittest discover -s tests -q`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **302 passed**.
  Eight new tests cover restart/reclaim attribution, concurrent same/competing
  plans, bounded validation, scopes/revocation/tenant isolation, stale or wrong
  workers, non-CSV/legacy rejection, insert rollback, real lease expiry during
  preparation, database constraints, runtime immutability and corrupt digests.
  The existing upgrade case also verifies that migration invents no plan inputs.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest
  discover -s tests`: **19 passed, 1 failed**, with the unchanged browser test
  reporting Chromium unavailable (503). No test was skipped or removed.
- `git diff --check`: passed.

Saved plans contain field names and coordinates only. They do not establish source
eligibility, extracted figures or accounting treatment. Next: use the saved plan
with the bounded decimal reader and current scan gate, committing an extraction
result/receipt under live job fencing and retry reconciliation. Scheduling,
providers, ledger posting, human final approval and production qualification remain
unfinished. No commercial UI work was started.

## C1 fenced CSV extraction execution — completed

Recovered clean `527bf7f`; checkpoint reports no divergence or dirty work.
Connect immutable saved CSV plans to the bounded reader and current scan gate.
Commit result and attributed job-effect receipt together under a locked live worker
lease; reject cancellation, stale inputs and expired workers. Preserve original
results on retries and keep figures outside job progress. No UI or live integration.


Migration 0057 and `execute_preparation_csv` connect exact saved plans to the bounded
CSV decimal reader and current evidence gate. The execute-only effect function
locks the job, verifies worker/token/lease, exact evidence ID/fingerprint and plan,
then commits the existing extraction result with first-worker attribution receipt.
It checks the database clock again after insertion. Retries preserve result,
provenance and original actor, including after worker recovery. Job progress stays
unchanged and the job remains running. Apply the additional function grant in
JOBS_POSTGRES.md; no direct extraction-table grants are needed.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2,
psycopg 3.3.8 binary adapter and dependencies pinned in requirements-http.txt:

- `cd commercial && python3 -m unittest discover -s tests -q`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **312 passed**.
  Ten new tests cover exact decimal/source provenance, unchanged progress,
  restart/reclaim attribution, concurrent retry receipts, current scope/revocation,
  tenant and lease rejection, cancellation/expiry/reclaim during reads, gate changes,
  conflicting results, corrupt plans, exact evidence IDs and atomic rollback on
  receipt failure, commit deadline and real lease expiry during result insertion.
  The existing upgrade test confirms no effect receipts are invented.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**.
  The unchanged browser test reports Chromium unavailable (503). No test was skipped
  or removed; no prototype or commercial UI files were changed.
- `git diff --check`: passed.

Identity resolution, byte admission and effect entry are separate transactions;
revocation cannot cancel already-admitted work or retract bytes. Current eligibility
uses the existing gate's snapshot boundary. The final lease check precedes commit;
it does not promise that commit itself happens before lease expiry. The internal
result writer trusts deterministic worker output and is not a model-facing endpoint.
No scheduler, OCR, model, ledger posting or live integration was enabled.
Next: recover a job-linked extraction receipt and unresolved-question summary through
current identity and evidence eligibility checks, then connect bounded clarification
and expense preparation. Production qualification and final human approval remain
unfinished. No active implementation remains in this increment.

## C1 job-linked CSV recovery summary — completed

Recovered clean `c140d05`; no active increment or competing writer recorded.
Add a live-worker, current-identity read of an exact saved-plan extraction receipt
and unresolved clarification summary. Keep source bytes and monetary values out
of this recovery surface; preserve human-only clarification writes and job progress.
Verify current scan eligibility, saved plan and source binding on every read.


Migration 0058 and `AuthenticatedJobStore.get_csv_summary` recover the original
extraction-effect receipt, exact source references and unanswered clarification
questions. A separate execute-only summary login reads job/lease, saved plan,
current source eligibility, result and human answers in one stable statement
snapshot. SQL validates candidate values/coordinates before redacting them; no
monetary values, original bytes or answer authors leave the database on this read.
Python validates the returned metadata and reuses the fixed clarification prompts.
Existing human-only answer storage is unchanged. Explicit unavailable answers are
counted separately and are not asked again; they do not become available amounts.
Apply the dedicated function grant in JOBS_POSTGRES.md. No data migration is needed.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2,
psycopg 3.3.8 binary adapter and the requirements-http.txt dependencies:

- `cd commercial && python3 -m unittest discover -s tests -q`: **46 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **320 passed**.
  Eight new tests cover restart/reclaim receipt recovery, human answers and
  unavailable outcomes, no repeated resolved questions, missing effect receipts,
  current scan-policy/blocked-verdict/live-scan checks, scope/revocation/role and
  tenant restrictions, wrong/expired/replaced/cancelled workers, dedicated grants,
  metadata-only database output, read-only transactions, context cleanup and corrupt
  result/plan/answer rejection. The existing migration upgrade case checks the
  new function while preserving original jobs and empty effect receipts.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**;
  unchanged browser case reports Chromium unavailable (503). No tests skipped or
  removed; no prototype or commercial UI code changed.
- `git diff --check`: passed.

This is a read-only observation, not a lease reservation, continuing eligibility,
posting authority or job-completion decision. Identity admission precedes the read;
revocation after admission and cancellation/scanner changes after the statement
snapshot cannot retract returned metadata. Every later effect must recheck current
authority/lease/eligibility. No progress or stored answers are changed by this read.
Next: persist validated expense-preparation context and connect the existing shared
preparation service to job-scoped retry receipts. Human clarification handoff,
scheduling, providers, ledger posting, final-package approval and full production
qualification remain unfinished. No active implementation remains in this increment.

## C1 saved expense-preparation inputs — completed

Recovered clean `c0f778e`; no unfinished increment or competing writer recorded.
Persist one immutable expense plan per CSV evidence task: exact saved source cell,
GBP currency, accounting date, configured period and eligible expense account.
Require current identity and worker lease, validate current bookkeeping policy on
saves/replays and preserve first attribution through recovery. Execution and
job-scoped expense effects remain a subsequent increment. No posting or UI work.


Migration 0059 and `ExpensePreparationPlan` persist exact source coordinates and
explicit GBP/date/period/account context per CSV evidence task. Composite foreign
keys bind the task organisation and configured accounting references; forced RLS
and append-only grants protect the new table. Signed save/read methods recheck
current authority. Saves serialize on the job, validate the parent CSV digest and
cell, current period/account policy and live worker lease, preserve first actor
and reject conflicting plans. A final database-clock check rolls back expired
saves. The existing human expense preparation path shares the input validator;
its human-only boundary is unchanged. Apply grants in JOBS_POSTGRES.md.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2,
psycopg 3.3.8 binary adapter and requirements-http.txt dependencies:

- `cd commercial && python3 -m unittest discover -s tests -q`: **47 passed**.
  New canonical-input coverage rejects implicit/extra monetary fields, unsupported
  currency, invalid references/coordinates and datetime instead of accounting date.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **328 passed**.
  Eight new tests cover first-attribution recovery after a different worker claims,
  current period/account/date/cell checks, concurrent same/competing initial writes,
  scope/role/revocation/tenant boundaries, wrong/expired/cancelled claims, failed
  inserts and real lease-expiry rollback, RLS/immutability/constraints/digest checks,
  and missing/corrupt parent plans. Upgrade retains existing jobs and invents no
  expense plans. Existing human preparation and policy behaviour remain covered.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**;
  unchanged browser case reports Chromium unavailable (503). No tests removed or
  skipped; no prototype or commercial UI code changed.
- `git diff --check`: passed.

A saved plan is historical intent, not evidence eligibility, amount availability,
expense creation or posting authority. Reads validate its digest and current read
authority; they remain available after policy closure. Save-time bookkeeping
configuration is a statement observation, not a reservation through commit or
execution. Identity admission and job work remain separate transactions; the final
lease check precedes commit. No source amounts, expenses, journals, clarification
answers or progress changes are created by saving a plan.
Next: execute saved expense plans using a separate job-fenced shared-service effect,
rechecking resolved source/current evidence/accounting policy and atomically storing
expense and retry receipt. Human clarification handoff, providers, scheduling,
posting, final approval and production qualification remain unfinished. No active
implementation remains in this increment.

## C1 fenced expense-draft execution — completed

Recovered clean `d3657d0`; no active increment or competing writer recorded.
Execute immutable saved expense plans through existing source-amount and expense
creators. Recheck signed identity, live worker/lease, exact plan/source/current
eligibility and accounting policy; atomically commit draft and job-effect receipt.
Preserve first attribution on recovered-worker retries, accept no worker-supplied
amount and leave progress/job completion/posting unchanged.


Migration 0060 and `AuthenticatedJobStore.execute_expense_plan` execute saved input
plans via the existing source-amount and expense creators. The worker submits no
amount or replacement accounting context. After recovering validated plans, fresh
signed identity is resolved again. SQL locks the job, verifies current worker/lease,
exact source/plan and job-backed extraction receipt, then atomically creates source
draft, expense draft and first-actor job receipt. Existing creators recheck current
source/accounting policy and hold their locks through commit. Recovered-worker
retries retain original attribution; both input digests are pinned in the receipt.
The result contains metadata only and leaves progress/job completion unchanged.
Apply the separate execute-only role grant in JOBS_POSTGRES.md. Existing human-only
preparation/clarification checks remain unchanged; the summary-role guard now also
rejects the new expense-write privilege.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2,
psycopg 3.3.8 binary adapter and requirements-http.txt dependencies:

- `cd commercial && python3 -m unittest discover -s tests -q`: **47 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **341 passed**.
  Thirteen new tests cover exact source-backed pence, first-attribution recovery,
  concurrent retry/cancellation, human clarification/unavailable answers, missing
  extraction receipts, nonpositive/fractional-penny rejection, current policy,
  scope/role/tenant/revocation and wrong/expired/terminal claims, receipt failure
  and real lease expiry rolling back all new rows, dedicated grants, preservation
  of another actor's preexisting source draft, fresh identity after input recovery
  and changed intent refusing the original receipt. Upgrade preserves existing
  jobs/plans and invents no effect receipts.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**;
  unchanged browser case reports Chromium unavailable (503). No test skipped or
  removed; no prototype or commercial UI code changed.
- `git diff --check`: passed.

This prepares an expense draft only: no funding choice, journal, ledger posting,
statutory approval or job-completion decision is made. No figure enters progress or
the worker's returned receipt. Membership revocation governs the next admission,
not an already-admitted transaction. Cancellation follows job-lock ordering and
preserves effects committed before it. Final lease verification precedes commit;
it does not promise commit finishes before expiry. The database role is a trusted
server capability, not customer authentication or a model-facing SQL tool.
Next: recover job-linked expense receipts/review under fresh eligibility, then save
explicit funding/counterpart intent before journal preparation. Human handoff,
scheduling, providers, ledger posting, final-package approval and production
qualification remain unfinished. No active implementation remains in this increment.

## C1 job-linked expense recovery summary — completed

Recovered clean `f487932`; no unfinished increment or competing writer recorded.
Recover the exact saved expense effect/plan through the shared current expense
read gate, with fresh identity, live worker lease and original receipt/digest/source
binding. Return metadata only; do not expose monetary values, mutate progress,
choose funding or record approval. Keep human review and write roles separate.


Migration 0061 and `AuthenticatedJobStore.get_expense_summary` recover the original
expense-effect receipt, canonical saved plan, source references/fingerprint,
scan-policy version, source kind and expense creation time. A separate execute-only
summary login uses a read-only transaction and one stable statement snapshot.
Existing CSV/expense read gates check live worker/lease, exact extraction/expense
effect and plan digests, resolved source, current scan and accounting policy. The
saved expense must match the job, selected source cell, context and original
expense/source creators. Amounts are checked inside PostgreSQL and redacted before
return; no monetary values or document bytes leave this function. No progress or
other record is changed. Apply the summary-only grant in JOBS_POSTGRES.md.

Verification on 7 November 2026 with Python 3.12, disposable PostgreSQL 16.2,
psycopg 3.3.8 binary adapter and requirements-http.txt dependencies:

- `cd commercial && python3 -m unittest discover -s tests -q`: **47 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`
  with disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **349 passed**.
  Eight new tests cover receipt/context recovery after different-worker reclaim,
  unchanged job rows, current scan/period/account gates, scope/role/revocation and
  tenant restrictions, wrong/expired/replaced/cancelled claims, missing effect and
  changed pence/context/creator/digest rejection, metadata-only SQL output, read-only
  transactions, dedicated grants/context cleanup, clarified sources and revocation
  during input recovery, and a receipt linked to another job's draft. Upgrade
  preserves existing records and verifies the new function is installed.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**;
  unchanged browser case reports Chromium unavailable (503). No tests skipped or
  removed; no prototype or commercial UI code changed.
- `git diff --check`: passed.

Recovery is a snapshot observation, not continuing eligibility, a lease reservation,
funding choice, human bookkeeping review decision, posting authority or approval.
Identity admission precedes the read; subsequent membership/source/policy/job changes
cannot retract already-returned metadata. Later effects must recheck current
identity, worker lease and eligibility. Existing human-only full expense review
remains separate. Next: persist explicit validated funding/counterpart intent before
connecting shared journal preparation to job-effect receipts. Human handoff,
scheduling, providers, posting, final-package approval and production qualification
remain unfinished. No active implementation remains in this increment.

## C1 saved funding/counterpart intent — completed (9 November 2026)

Recovered clean remote `fdf4b08`; no active task or competing writer recorded.
Persist explicit payer/funding kind/source/counterpart intent for the exact
job-backed expense under fresh identity and a live worker lease. Preserve first
attribution and parent plan digests on retry. This increment must neither record
actual funding nor create/post a journal or approve a package.

Migration 0062 adds forced-RLS intent storage with composite organisation, mapping
and exact expense-effect references. `JournalPreparationPlan` requires explicit
nonzero source/payer/counterpart IDs and a supported funding kind; strict canonical
serialization accepts neither an amount nor approval fields. The signed service
recovers both parent plans, resolves identity again, and admits the write through
a dedicated execute-only login. SQL locks the job, reuses the shared expense read
gate and checks the exact enabled source/payer/kind/counterpart mapping. Funding
and counterpart policy rows remain share-locked through commit. Same-account
counterparts are rejected. Retries preserve first attribution and both parent
digests; changed intent conflicts without overwriting. Decode failure or actual
lease expiry during insertion rolls back new intent. Historical read validates
the saved plan digest and requires fresh record-read authority. Grants and limits
are documented in commercial/JOBS_POSTGRES.md.

Verification on 9 November 2026 with Python 3.12, disposable PostgreSQL 16.2,
psycopg 3.3.8 and the existing pinned requirements-http.txt environment:

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`, with
  disposable-cluster OMNIXAT_TEST_ADMIN_DSN: **358 passed** in 48.018 seconds.
  Nine new integration tests cover reclaimed-worker attribution, exact mapping and
  expense eligibility, changed intent/parent digest conflicts, scopes/revocation/
  tenant/terminal claims, concurrent retry and decode rollback, dedicated grants,
  real lease expiry rollback, identity revocation during parent recovery, forced
  tenant filtering, composite binding and historical read after cancellation.
  Tests verify that no actual funding, journal or review-decision rows are created.
  Upgrade preserves old jobs/plans and creates an empty intent table.
  One new test initially compared a returned UUID to a string; its expectation was
  corrected before this final successful full run.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**;
  unchanged browser case returns 503 because Chromium is unavailable. No test was
  skipped or removed. No prototype or commercial UI code changed.
- `git diff --check` and staged whitespace review: passed.

This stores proposed intent only. It does not record funding, create/post a journal,
complete a job or approve a package. Existing human-only services remain unchanged.
Expense eligibility is observed at the shared read statement snapshot, not reserved
through later execution. Identity revocation governs subsequent admission; the final
lease check precedes commit, not a guarantee of commit before expiry. The dedicated
SQL role is a trusted server capability, not customer/model authentication. No live
provider, dependency upgrade or legal-rule change is included.

Next resumable step: connect saved explicit intent to job-bound shared journal
preparation with atomic retry receipts and fresh policy/claim checks; qualify the
agent preparation authority explicitly while preserving human review, posting and
statutory approval boundaries. Human handoff, scheduling, providers and production
qualification remain unfinished. No active implementation remains in this increment.

## C1 PostgreSQL migration execution bounds — completed (9 November 2026)

Recovered remote `2c19c46` and detected a concurrent customer-website writer in the
canonical checkout. This task uses isolated worktree
`/srv/playground_dev/OmniXat-persistence-20261109`; do not change that writer's work.
Scope: bound migration lock/statement waits, reject gaps in applied migration
history before executing SQL, and exercise migration with a non-superuser owner.
Validate real lock contention, timed-out DDL rollback and retry, session-setting
restoration and existing suites. No schema replacement, live integration or deployment.

Implemented transaction-local 5,000 ms lock / 60,000 ms statement defaults before
migration advisory locking, explicit validated bounded overrides, and rejection of
non-prefix migration history before pending SQL. Existing migration SQL is unchanged.
Six new real PostgreSQL tests cover competing migrators, table locks, timed-out DDL
and receipt rollback, explicit retry, setting restoration, history gaps, invalid
configuration, and complete schema install/repeat under a constrained database owner.

Verification (9 November 2026), in the isolated worktree:

- `cd commercial && python3 -m unittest discover -s tests -v`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -v`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -p test_migration_execution.py -v`:
  **6 passed** against disposable PostgreSQL **16.2**, psycopg **3.3.8**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`:
  **364 passed**, including those six tests; **433 commercial tests total**.
  Optional dependencies came from an existing local directory via PYTHONPATH;
  OMNIXAT_TEST_ADMIN_DSN was set only for a temporary local cluster.
- `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s tests -v`:
  **19 passed, 1 failed**, unchanged browser approval/idempotency case returning 503.
  Direct Chromium launch confirms `socket() failed: Operation not permitted`.
  No tests removed or skipped; no full-suite-green claim.
- `git diff --check`: passed. Official PostgreSQL 16 timeout documentation rechecked
  on 9 November 2026; see commercial/POSTGRES.md.

Limits: timeouts bound individual database lock/statement operations, not the whole
batch or connection acquisition. Constrained-owner tests prove schema installation,
not complete production definer-function/restore qualification. PostgreSQL 16.2 is
the available test runtime, not a maintained production-version recommendation.
No credentials, real records, schema replacement, provider, billing, filing or
public service was introduced. No active work remains in this isolated increment.

Next resumable step: recover the separate customer-website work from the canonical
checkout without overwriting its dirty files, fetch and deliberately integrate this
published migration increment before publication. Continue database qualification
on the maintained target version, including constrained-owner service execution and
restore. Job-backed journal preparation remains an independent product increment.

## C2 customer website — implemented; browser/provider qualification pending (9 November 2026)

Owner priority now explicitly includes the complete functional customer website.
Recovered clean `2c19c46`; no other active writer recorded. Focus this increment on
an authenticated, responsive customer workspace using the existing PostgreSQL
record services: discover only current memberships, browse/create organisations,
read/create persistent notes, preserve creation retry keys, and enforce viewer,
revocation, tenant and browser-origin boundaries. Add real Chromium coverage and
run the unchanged fictional-demo browser case. No billing activation, filing,
deployment or fabricated dashboard figures. Further accounting/evidence, billing
and owner journeys remain required production work, not pretend navigation.

Implemented the commercial customer website (`commercial/web`, `customer_web` and
an explicitly configured ASGI server factory), not a replacement of the old demo.
It provides a public entry page, workspace discovery/switching, paginated
organisation browsing/creation and persistent organisation notes. Desktop/mobile
layouts, keyboard labels/dialog, empty/loading/error/read-only states and filters
are included. UI counts are loaded rows, not financial/owner metrics. User text is
rendered with textContent. Bearers and private drafts never enter browser storage.
Pending saves retain an immutable payload/key in page memory; a lost response can
be retried without a second record. Pending/unsaved notes block context switching.
Closing a page still needs manual record reconciliation before re-entry.

Migration 0063 adds a bounded, subject-scoped directory capability with a dedicated
execute-only login and owner-only RLS directory policies. Existing record runtime
remains tenant scoped. A user/tenant index supports membership lookup. Directory
and record reads resolve current identity/membership, including revocation/cutoff;
creation reuses existing validated/audited/idempotent services. Context and bounded
cursor lists are shared API capabilities, not separate frontend database logic.
An additional test executes the directory under a non-bypassing migration owner.

The same-origin browser boundary independently verifies access tokens passed by an
operator-managed maintained OIDC gateway; it does not trust role/email/tenant
headers. Exact Origin/Fetch Metadata checks protect writes. CSP, no-store,
no-referrer, allowlisted assets and private DSN files are enforced. The app factory
bounds database admission/connect waits; a non-root Dockerfile and operator gateway
template are supplied. See CUSTOMER_WEB.md for required setup and exact limits.
No provider realm, customer credential, public host or container was activated.

Remote movement was reviewed before publishing: `5660349` added bounded migration
execution and six tests while this website was being written. Website changes were
preserved in stash `69f8a6eccbc2c33570eee781ede6f49645375607`, the clean checkout
fast-forwarded, and the stash reapplied. Only the append-only status conflicted;
both complete histories were retained. The migration function changes and its tests
are preserved. The final combined suite below includes both increments.

Verification on 9 November 2026 (Python 3.12, PostgreSQL 16.2, existing pinned
psycopg/HTTP/identity dependencies; Uvicorn 0.52.1 and Playwright 1.62.0):

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`, with
  disposable OMNIXAT_TEST_ADMIN_DSN: **371 passed** in **52.112 seconds** on the
  reconciled branch; **440 service tests total**. Seven new tests cover directory
  scope, revocation/cutoff, RLS cleanup/direct grants, constrained-owner execution,
  paging/parent/tenant/role checks, browser origin/headers and startup configuration.
- Supplemental JSDOM 26.1.0 interaction diagnostic against actual ASGI/PostgreSQL
  services: **passed**, including organisation creation, note save, a response lost
  after commit and same-key retry yielding one row, navigation/filtering, unsaved
  note protection, safe literal untrusted text and no browser storage. This is DOM
  logic evidence, not actual-browser/layout or OIDC-provider qualification.
- `node --check commercial/web/app.js`, gateway-template TOML parse and
  `git diff --check`: passed.
- `cd commercial && PYTHONPATH=.:integration_tests OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s browser_tests -v`:
  **2 errors**, both blocked before page load by host policy (`socket() failed:
  Operation not permitted`). The supported Playwright headless-shell download also
  failed as a truncated archive. These are retained real Chromium tests, not skipped
  or replaced by the DOM diagnostic. No actual browser/visual success is claimed.
- `cd prototype && python3 -m unittest discover -s tests`: **19 passed, 1 failed**;
  unchanged approval/idempotency browser case returns 503 with Chromium unavailable.
- Local Docker build: **not run**, Docker is unavailable. A CI build step is included.

`.github/workflows/commercial.yml` defines PostgreSQL service tests, the real Chromium
customer workflow, container build and unchanged prototype suite on a supported
runner, with read-only repository permission and pinned checkout/setup actions.
Its actual run status must be inspected after publication; merely adding CI does
not establish a passing check. Existing prototype tests were not changed/skipped.

Next resumable step: inspect this commit's CI and resolve any real browser/container
failures, then qualify the maintained browser sign-in/gateway with the exact access
profile, session expiry/logout and revocation. Continue the customer-facing evidence
upload and draft-review journey against existing services, then subscription and
owner workflows. Do not return to unrelated worker micro-increments. The complete
platform is not yet production ready: live login qualification, remaining accounting
and UI flows, private draft recovery, accessibility/security/load/restore evidence,
billing/provider and statutory module qualification remain required. No active
writer remains after publication; the preserved stash is a recovery backup, not
an unfinished competing implementation.

### Password-authenticated CI follow-up

The first published CI run for `b66f082` installed Chromium successfully and the
unchanged prototype passed **20/20**, including its real browser approval test.
Its service step ran 371 tests but reported 34 errors because several test/admin
reconnects used `Connection.info.dsn`, which deliberately omits passwords. This
was hidden by local trust authentication. No production authentication was weakened.
Fixtures now retain the original operator-supplied DSNs in process for administrative
reconnects; explicit constrained-role credentials remain separate. No credential
value is committed or printed by this change.

Verification after the fix: **371 integration tests passed in 53.312 seconds**
against a separate disposable PostgreSQL 16.2 cluster with SCRAM-SHA-256 required
for host/local authentication and a generated private test password. Together with
48 core and 21 identity tests this remains **440 passing service tests**. The CI
health probe now names its database. CI also retains fictional desktop/mobile
screenshots for visual review when the real customer browser suite succeeds.
Next: inspect the new CI run, resolve any actual UI/build failures, and then qualify
real maintained sign-in before extending evidence/draft-review journeys.

### Supported-runner browser and build evidence

GitHub run https://github.com/EnigmaThe1/OmniXat/actions/runs/42711977745 for
`51a1ba8` completed successfully on Ubuntu 24.04, Python 3.12.16, PostgreSQL 16.15:
**48 core + 21 identity + 371 integration + 2 real Chromium customer + 20 unchanged
prototype tests = 462 passed**, plus a successful non-root customer container build.
The service integration run took 68.283s and the customer browser run 2.676s.
The actual desktop/mobile screenshots were downloaded and visually inspected:
readable layout, working filtered organisation view, no horizontal mobile overflow.
This closes the environment-only browser/build blocker for that tested commit;
it does not qualify a real OIDC provider/gateway or the entire SaaS.

A final session-expiry review identified that the organisation dialog needed its
own accessible sign-in link after a 401. It now exposes that recovery action while
preserving the unconfirmed retry state. The public entry page's skip link targets
its visible main content. A third real-browser test uses an actually expired signed
JWT to verify the dialog's sign-in/retry state and zero created organisations.
CI now also captures the public entry and notes screen. Inspect the latest run for
this additional regression; do not confuse the prior 462 result with this new case.

### Final customer regression and controlled prototype browser

CI for `c05dd6d` passed **440 service tests + all 3 real Chromium customer tests**
and the container build, including the expired signed-token dialog case. Its
unchanged prototype suite ran all 20 tests but one browser HTTP request timed out;
the previous supported-runner run had passed all 20. The workflow now explicitly
selects the browser installed by pinned Playwright for that suite, using its existing
OMNIXAT_CHROMIUM_PATH configuration, instead of falling back to whatever system
Chromium/Chrome the runner provides. Test code, assertions and timeouts are unchanged.
This removes a browser-version variable; it does not prove the cause of the prior
timeout. Inspect the next CI result rather than describing a rerun as prior success.

## C2 customer evidence intake — completed and CI verified (9 November 2026)

Recovered clean remote `6d6ffde`; its GitHub verify check passed, including the
retained prototype browser test. No open PR targets this development head. Work
uses isolated `/srv/playground_dev/OmniXat-evidence-20261109` to avoid other writers.
Scope: opt-in bounded raw-file upload into existing evidence staging/registry/
quarantine services and a paginated customer evidence list. Resolve fresh signed
human membership and explicit evidence scopes; preserve same-content retry receipts,
viewer/tenant/revocation boundaries and private spool cleanup. Show quarantine
status without claiming scanner/extraction/accounting completion. Add database/API
and real-browser regressions; no provider, billing, posting, filing or deployment.

Implemented opt-in raw-file POST and cursor-paginated GET on each organisation's
`/evidence` resource, plus a responsive evidence panel in the customer website.
Uploads use the existing staging, fingerprint registry and write-only PostgreSQL
quarantine services; there is no replacement schema or direct original-byte read.
A private service-owned spool, constrained grants and explicit record/evidence scopes
are required. All writes preserve human-only evidence registration. Fresh database
identity/membership checks run before body intake, after staging and before storing
payload; caller role/actor claims cannot elevate access. Limits cover actual bytes,
Content-Length, duplicate/unsupported headers, 15-second body receipt and four active
uploads per app/process. Anonymous spools close on errors, timeout and disconnect.

The evidence list distinguishes metadata-only interrupted uploads from stored
quarantine receipts. Exact same-file/type retry preserves the first registration and
storage receipt. The UI holds an uncertain File/type in memory, blocks edits and
navigation until retry resolves, safely displays metadata, and hides upload controls
for viewers or missing scopes. Filename, content and tokens never enter browser
storage. Upload does not schedule processing, release an original, scan, extract,
post accounting entries or record human approval.

Verification on 9 November 2026 (isolated worktree, Python 3.12, PostgreSQL 16.2):

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -p test_customer_evidence.py -v`:
  **12 passed**, including actual concurrent uploads, payload-read privilege denial,
  tenant/parent binding, role/scopes/agent denial, expiry/revocation, partial receipt
  recovery, paging/conflicts, duplicate/truncated headers and ASGI timeout/disconnect.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`:
  **383 passed in 43.249s**, including all 12 new cases; **452 service tests total**.
  Tests used an explicitly disposable local cluster and existing pinned dependencies
  through PYTHONPATH; no DSN/credential/log was committed.
- `cd commercial && PYTHONPATH=.:integration_tests OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s browser_tests -v`:
  **5 errors before page load**, host Unix-socket denial. The two new real Chromium
  cases exercise upload/reload/duplicate/viewer/mobile and a response lost after commit
  followed by exact-file retry. CI must prove them; no browser success claimed here.
- Unchanged prototype suite with explicit Chromium: **19 passed, 1 failed** at the
  browser approval test returning 503 under the same host restriction. No skip,
  assertion, timeout or prototype-source change.
- `node --check commercial/web/app.js` and `git diff --check`: passed.

Limits: declared format is not validation or a malware verdict. Intake commits
registration separately from payload and makes interruption visible; revocation
cannot retract already admitted transactions. Browser selections/retry state are
memory-only. Four uploads is a per-process bound, not a tenant quota. Private storage,
capacity, encrypted backups, retention, payload-free logs, gateway buffering, scanner
and exact provider access-token/session qualification remain real-use prerequisites.
See CUSTOMER_WEB.md for setup/grants and checked primary technical references.
No live bank/model/scanner, billing, ledger posting, filing or deployment was enabled.

Next: inspect this commit's CI services/browser/container/prototype checks and actual
screenshots, fix any failure, then qualify the maintained login/gateway and connect
an authorised scanner and evidence/draft-review journey. No local implementation is
unfinished; real-browser qualification is pending publication. Preserve the full
customer website rather than returning to unrelated worker-only increments.

### Supported-runner evidence intake verification

[GitHub run 42717514445](https://github.com/EnigmaThe1/OmniXat/actions/runs/42717514445)
for published implementation `7d87fcf` completed successfully on 9 November 2026:
**48 core + 21 identity + 383 PostgreSQL/HTTP + 5 real Chromium customer + 20
unchanged prototype tests = 477 passed**, with a successful customer container build.
PostgreSQL was **16.15**; service integration took **60.630s**, customer browser
**6.127s**, prototype **3.161s**. All steps passed; no skipped tests or prototype
assertion/timeout changes. The published tree was fetched and exactly matched the
locally tested source. The captured mobile evidence screenshot was downloaded and
visually inspected: readable saved receipt and format/upload controls, wrapping
record identifier and no horizontal overflow. The browser test additionally asserts
no overflow, duplicate suppression, viewer controls and memory-only selection state.

This closes the new upload browser/build qualification for that code revision.
Local host Chromium restrictions persist; CI is the actual-browser evidence. The
server-side gateway stand-in does not qualify an external OIDC realm/session,
scanner, storage/retention/restore or the complete accounting platform. No active
implementation or failed CI remains for this increment. Next: qualify maintained
login/gateway, then connect authorised scanning and customer evidence/draft review
against the existing validated services; retain quarantine and human approval gates.

## Customer evidence recovery hardening — implemented; CI pending (9 November 2026)

Recovered the unpublished evidence tree and verified it equals remote `7d87fcf`.
A concurrent writer published that increment; its checkout is left untouched.
This follow-up uses `/srv/playground_dev/OmniXat-recovery-20261109` from that remote.
Scope: preserve exact-file retry and sign-in recovery when a signed token expires
between upload admission and storage, distinguish membership denial, and give
useful format/size rejection messages. Add real PostgreSQL and Chromium regressions.
No provider, scanner, billing, deployment or statutory action is enabled.

Implemented token revalidation on a denied evidence operation: an expired/invalid
bearer returns 401 so the browser keeps the original File/format for sign-in and
exact-file retry. A still-valid token with revoked membership remains 403. Upload
conflict, size and format errors now explain the corrective action without exposing
server diagnostics. No identity, scope, expiry or human-only gate was relaxed.

Verification in the isolated worktree (9 November 2026):

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -p test_customer_evidence.py -v`:
  **13 passed** on disposable PostgreSQL 16.2, including signed-token expiry after
  staging and after registration, cleanup and same-original recovery. JWT time is
  advanced only in that fixture; signatures and expiry validation remain real.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`:
  **384 passed**, **453 service tests total**, using disposable local cluster DSN
  and existing pinned dependencies supplied through PYTHONPATH. Initial fixture
  clock lifetime/type failures were corrected before this complete passing rerun.
- `node --check commercial/web/app.js`, Python compilation and `git diff --check`:
  passed. Two additional actual Chromium regressions cover expired-token retry and
  correcting a conflicting format without losing the selected file. Local Chromium
  remains blocked by the previously confirmed host Unix-socket restriction; these
  new cases must pass on CI before a combined-suite success claim. No test skipped.
- Base `7d87fcf` CI run 42717514445 independently passed 477 tests and Docker build.
  The concurrent documentation-only `b3a372e` was reviewed and fast-forwarded while
  preserving this scope in a recovery stash; both status histories are retained.

Checked primary references on 9 November 2026: [HTTP status semantics](https://www.rfc-editor.org/rfc/rfc9110.html#name-status-codes)
and [PyJWT expiration validation](https://pyjwt.readthedocs.io/en/stable/usage.html#expiration-time-claim-exp).
No dependency versions, provider or legal rules were changed.

Limits: a fresh token in a browser fixture is a gateway stand-in, not a qualified
maintained-provider refresh/login. Retry state remains page-memory only. Existing
quarantine, private storage, retention/restore and scanning prerequisites persist.
No deployment, billing activation, posting or statutory action occurred.
Next: inspect this follow-up's CI including all seven customer Chromium cases and
the unchanged 20-test prototype, then qualify maintained sign-in/session and the
scanner/draft-review journey. No active implementation remains in this follow-up.

## Customer evidence receipts — implemented; CI pending (10 November 2026)

Recovered clean remote `796de6c`; connected GitHub verify check passed. No open PR
uses this development branch, no other checkout or active implementation process
was found, and checkpoint reports zero divergence. Scope: tenant/organisation-bound
read-only evidence receipt endpoint and accessible customer receipt details showing
server-computed SHA-256, declared format, size and registration/storage timestamps.
Preserve quarantine and all current identity/scope/revocation boundaries. Add real
PostgreSQL/HTTP and Chromium regressions. No originals, scanning, extraction, billing,
provider activation, deployment or statutory action. Existing review/scanner services
remain independent; this increment makes upload provenance inspectable by customers.

Implemented opt-in GET/HEAD receipt metadata through the existing customer evidence
controller and runtime grants. Rechecks current membership and read scopes before
reading, constrains tenant/organisation/evidence together, and keeps originals
unreadable to the runtime login. Responses contain only receipt ID, organisation,
declared format, byte count, server-computed SHA-256 and registration/storage times.
No migration, new grant or processing trigger. List payloads remain unchanged.

Customer rows now expand a fresh receipt on demand, with loading/error/retry,
accessible region/expanded-state controls, mobile wrapping and explicit incomplete
upload status. Closing clears displayed metadata; expiry/access denial hides the
workspace and offers existing sign-in recovery. Nothing enters browser storage.
The receipt explains that a fingerprint is not a scan, extracted amount, accounting
entry or approval. CUSTOMER_WEB.md documents the endpoint and exact boundaries.

Verification on 10 November 2026 (Python 3.12, existing pinned dependencies):

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  explicit disposable test admin DSN: **389 passed in 36.776s** on PostgreSQL
  **16.15**, UTF8, SCRAM-required TCP authentication; **458 service tests total**.
  Five new cases cover exact fingerprint/metadata allowlist, no payload/actor
  disclosure, HEAD, tenant/parent/viewer/revocation, second authority check, partial
  registration recovery, scopes/expiry, request validation and disabled routes.
  The initial local cluster used SQL_ASCII and returned text as bytes; it was
  replaced by a separate UTF8 cluster before the complete passing run. A new
  cache-header assertion was corrected to account for both existing boundaries'
  no-store headers. No production guard or dependency version was changed.
- `cd commercial && PYTHONPATH=.:integration_tests OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s browser_tests -v`:
  **9 errors before page load**, host `socket() failed: Operation not permitted`.
  Two new retained real-browser cases cover viewer fingerprint details, 503 retry,
  closing/clearing, mobile overflow/storage and expired-token sign-in protection.
  Playwright's browser download also failed as a truncated archive. CI must verify
  actual browser operation; no local browser success or screenshot review claimed.
- Unchanged `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s tests -v`:
  **19 passed, 1 failed**, browser approval case returns 503 with Chromium unavailable.
  No skip, assertion or timeout change.
- `node --check commercial/web/app.js`, Python compilation and `git diff --check`:
  passed. Docker build is left to the existing CI; Docker is unavailable locally.
- Connected GitHub inspection confirmed recovered `796de6c` had a successful verify
  check (run 42718577174), closing its previously pending recovery-hardening CI.

Limits: receipt metadata describes registration/storage, not scanner/extraction or
ledger progress. Hashes are private workspace metadata. Provider login/session,
scanner authorisation, quotas, retention/restore and remaining customer/owner
journeys still require qualification. No original download, real evidence, secret,
billing activation, deployment or statutory action was introduced.

Next resumable step: inspect the published receipt CI including all nine customer
Chromium cases, retained prototype browser and container build; fix any actual
failures and inspect the receipt mobile screenshot. Then qualify maintained
login/session and connect authorised scanner/draft review to the customer journey.
No active implementation remains after publication.

## Customer session recovery continuity — implemented; CI pending (10 November 2026)

Recovered clean remote `c03c05b`, zero divergence, no other local writer or checkout.
Connected GitHub run 42748219198 passed 48 core + 21 identity + 389 integration +
9 actual Chromium customer + 20 retained prototype tests (487 total) and container
build. Receipt qualification is complete; screenshot inspection is recorded only
if actually performed. Scope: keep pending files/record saves in their original tab
while renewing sign-in in a separate noopener tab; independently verify the renewed
session before showing return instructions. Bind browser writes to the initiating
persisted actor so changing account during recovery cannot replay an uncertain save
under another actor's idempotency namespace. Add database and actual-browser tests.
No auto-save, browser draft/token storage, provider deployment, billing or filing.

Implemented separate-tab sign-in recovery and a minimal return page which verifies
the renewed signed session through the existing bounded directory service. Original
work stays in page memory; no opener reference, token handoff, browser storage or
automatic write is used. Pending organisation/note payloads, keys and original Files
are retained for explicit retry. A fresh session under a different account receives
409 session_changed and preserves pending state rather than using a different actor's
creation-receipt namespace. The expected actor header only restricts already resolved
authority; it cannot authenticate or grant permission. No migration/grant changes.

Verification on 10 November 2026 (Python 3.12, existing pinned dependencies):

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -p 'test_customer*.py' -v`:
  **28 passed**, including three new database/API continuity and boundary cases.
- `cd commercial && python3 -m unittest discover -s integration_tests -v`, with
  explicit disposable OMNIXAT_TEST_ADMIN_DSN: **392 passed in 101.894s**, PostgreSQL
  **16.15**, UTF8 and SCRAM-required TCP authentication; **461 service tests total**.
- `cd commercial && PYTHONPATH=.:integration_tests OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s browser_tests -v`:
  **13 errors before page load** from the host's Chromium Unix-socket prohibition.
  Four new retained actual-browser cases cover a separate recovery tab preserving
  the organisation save/File, opener isolation, invalid-session recovery, and a
  committed/lost-response note followed by account switching and same-account retry.
  CI must qualify these; no browser success claimed for the new increment locally.
- Unchanged `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s tests -v`:
  **19 passed, 1 failed** at the retained browser approval case (Chromium unavailable).
- `node --check commercial/web/app.js`, Python compilation and `git diff --check`:
  passed. Local Docker is unavailable; retain the existing CI container build.

Recovered receipt CI [run 42748219198](https://github.com/EnigmaThe1/OmniXat/actions/runs/42748219198)
passed **487 tests** (48 core, 21 identity, 389 integration, 9 customer Chromium,
20 unchanged prototype) and container build. Logs were inspected. Its actual
customer-receipt-mobile.png was downloaded and visually inspected: readable content,
wrapping fingerprint/IDs and no horizontal overflow. This closes the prior receipt
CI/screenshot checkpoint; it does not qualify this increment's new browser cases.

Primary OAuth2 Proxy endpoint/redirect and browser noopener sources were checked
on 10 November 2026 and linked in CUSTOMER_WEB.md. No dependency version or legal
rule changed. The gateway redirect in browser fixtures is a stand-in; exact external
provider, session-cookie renewal, key rotation, recovery and provider logout still
require qualification. The recovery page checks a signed session, not continuing
authority to save: every actual write independently resolves current membership.
Closing/reloading the original tab still loses memory-only work. No deployment,
real credentials/evidence, provider activation, billing or statutory action occurred.

Next resumable step: inspect this commit's CI including all 13 actual Chromium
customer cases, unchanged prototype and container, then inspect the recovery mobile
screenshot and fix any failures. Qualify the exact maintained provider/gateway
flow next, followed by authorised scanner and customer draft review. No active
implementation remains after publication.

### Recovery browser fixture follow-up

Published `e58d8bc` CI run 42753788667 passed **461 service tests** and all **20
unchanged prototype tests**. Customer Chromium ran all 13 cases: **11 passed**,
one upload fixture raced its initial workspace load before expiring its token,
and the separate-tab fixture's fulfilled 302 did not route its follow-up URL
through the local ASGI stand-in. The container step was consequently skipped.
The account-switch/lost-response and invalid-session regressions passed.

Fixtures now wait for the evidence panel before expiring the token and explicitly
complete the fictional hosted login in the opened tab before exercising the actual
return page/API/database. No assertion, timeout, application guard or prototype
code was removed or weakened. This remains gateway simulation, not live provider
qualification. Inspect the follow-up CI and recovery mobile screenshot.

### Supported-runner session recovery verification — complete

[Run 42754414906](https://github.com/EnigmaThe1/OmniXat/actions/runs/42754414906)
for published `5c806e9` completed successfully on 10 November 2026:
**48 core + 21 identity + 392 PostgreSQL/HTTP + 13 real Chromium customer + 20
unchanged prototype = 494 tests passed**, plus the customer container build.
Integration took **50.656s**, customer browser **10.834s**, prototype **2.932s**;
PostgreSQL was **16.15**, Python **3.12.16**. Logs confirm all four new recovery
regressions passed, including the retained exact-file/request retry and account
switch checks. No test was skipped or weakened. The earlier fixture failures are
resolved; this supersedes the pending-CI instructions above.

The actual customer-session-recovery-mobile.png from that run was downloaded and
visually inspected: readable return/same-account instructions, correct explicit
statement that the check has saved nothing, and no horizontal overflow. Browser
assertions also confirm null opener, preserved original tab/File, one saved record
and no browser storage. The tested published tree was fetched and matched the local
source. This final follow-up records evidence only; application/test code is unchanged.

Next: qualify the exact maintained gateway/provider session, cookie renewal,
revocation/key rotation and provider logout with fictional accounts, then connect
authorised scanning and customer draft review. No external provider/session or
whole-platform production qualification is claimed by these stand-in browser tests.
No deployment, paid activation or statutory action occurred. No unfinished local
implementation or failed CI remains for this increment.

## Maintained customer identity qualification — implemented; CI pending (10 November 2026)

Recovered clean remote aeff9c2 with zero divergence and successful verify check;
no active local writer, other checkout or unfinished implementation was found.
Scope: an opt-in, disposable Keycloak 26.8.2 qualification harness with generated
fictional credentials and verified loopback TLS. Exercise actual authorization-code
and S256 PKCE login, RFC 9068 access-token profile, replay/mismatch rejection and
existing tenant-scoped HTTP/PostgreSQL services. Pin the official release archive
SHA-256 in CI. Production token checks remain unchanged. No public realm, external
account, gateway activation, billing, statutory operation or private record.
Gateway cookies/browser redirects, MFA/recovery and full production identity
qualification remain subsequent acceptance work; do not claim them from this slice.

Implemented the opt-in qualification package and five real-provider/PostgreSQL/HTTP
cases. A checksum-pinned official archive installer and Java 21 CI step run a fresh
Keycloak 26.8.2 process on verified loopback TLS. Private files contain only generated
fictional credentials, account, certificate and isolated H2 state, and are cleaned up
with the process. No ambient database/GitHub/proxy credentials are passed to it.
No production factory, verifier, grant or schema was changed.

Real form login/code exchange uses exact callback/state/response issuer, S256 and
ID-token nonce verification. The minimal RFC 9068 client explicitly maps subject,
API audience and client_id; records:read is default and records:write optional.
The actual provider initially omitted access-token sub and was correctly rejected
by the unchanged verifier; the explicit subject mapper fixes the provider profile.
Actual provider ID tokens/wrong audiences are rejected by the API verifier.
Refreshed tokens retain the profile; rotated refresh/code reuse and wrong PKCE
are rejected. Password/service-account grants remain disabled. Provider-signed
read-only tokens, viewer/cutoff/unprovisioned identities and other tenants cannot
obtain record writes. Authenticated attributed note creation/replay still uses the
same database services. See KEYCLOAK_CUSTOMER_QUALIFICATION.md for exact limits.

Verification on 10 November 2026 (Python 3.12, Java 21.0.13, PostgreSQL 16.15
UTF8 with SCRAM-required disposable-cluster TCP authentication):

- `cd commercial && python3 -m unittest discover -s tests -q`: **48 passed**.
- `cd commercial && python3 -m unittest discover -s identity_tests -q`: **21 passed**.
- `cd commercial && python3 -m unittest discover -s integration_tests -v` with
  explicit disposable OMNIXAT_TEST_ADMIN_DSN: **392 passed in 50.631s**.
- `cd commercial && PYTHONPATH=.:integration_tests python3 -m unittest discover -s provider_tests -v`
  with OMNIXAT_KEYCLOAK_HOME pointing to the checksum-verified official archive:
  **5 passed in 29.829s** against actual Keycloak 26.8.2; **466 service/provider
  tests total**. No HTTP provider response or signed token is mocked. Fixture
  startup/import, per-test identity cleanup and OAuth error-response expectations
  were corrected before this complete passing run. The missing-PKCE case asserts
  an exact invalid_request callback and absence of code; disabled grants assert
  unauthorized_client, rather than assuming all OAuth rejections have HTTP 400.
- Existing `cd commercial && PYTHONPATH=.:integration_tests OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s browser_tests -v`:
  **13 errors before page load**, the known host Unix-socket prohibition.
- Unchanged `cd prototype && OMNIXAT_CHROMIUM_PATH=/usr/bin/chromium python3 -m unittest discover -s tests -v`:
  **19 passed, 1 failed** at the retained browser approval case (Chromium unavailable).
  No browser case/assertion/timeout was changed or skipped. New CI must exercise
  the full combination; the recovered aeff9c2 verify check had already passed.
- Shell syntax, Python compilation, workflow YAML parse and `git diff --check`:
  passed. Local Docker is unavailable; preserve the existing CI container build.

Primary release checksum metadata, pinned Keycloak mapper/config source and runner
Java inventory were checked on 10 November 2026 and linked in the new guide.
Production dependencies and legal rules are unchanged. This is actual provider
protocol/service compatibility, not browser/gateway or whole-platform production
qualification. The fixture still omits production email/MFA/recovery flows and
operator key approval/rotation. No real account, deployment, bank/model/scanner,
payment activation or statutory action occurred.

Next resumable step: inspect this commit's verify check including the new native
provider step, all 13 customer Chromium cases, retained prototype and container.
Resolve any CI environment/code failure. Then extend the qualification harness
with actual OAuth2 Proxy/browser login, cookie renewal/account switch/logout and
provider key/session revocation; connect that qualified journey to authorised
scanner and draft review. Do not substitute these HTTP form tests for the actual
browser/gateway acceptance matrix. No active implementation remains after publication.

## Restore complete CI qualification — in progress (10 November 2026)

Recovered clean f95392d. Run 42760709436 exhausted its 20-minute budget inside
Playwright's APT dependency setup: logs show repeated Azure Ubuntu mirror retries
and stalled package indexes. No service/provider/customer browser test ran; the
retained prototype browser failed because Chromium was not installed. This is not
a passing qualification result. Scope: repair Ubuntu hosted-runner package setup
using official HTTPS Ubuntu sources, verified archive signing and bounded network
retries, preserving every existing test and production dependency.

Implemented a hosted-Ubuntu-24.04-only preparation step. It replaces the runner's
Ubuntu mirror indirection with https://archive.ubuntu.com/ubuntu/ for all four noble
pockets, retaining the Ubuntu archive signing key and all components. APT transport
timeouts are 30 seconds with two retries and update errors fail closed; dependency
installation has an eight-minute step budget. No TLS/package signature verification
is disabled. These commands run only on the ephemeral GitHub-hosted runner, not the
application host. All service, real-provider, customer browser, container and retained
prototype steps remain. No test code/assertion/timeout was changed.

Verification: workflow YAML parsed, `bash -n` passed for every embedded run block,
structural checks confirmed both browser steps remain (prototype still always()),
and `cd commercial && python3 -m unittest discover -s tests -q` passed 48 tests in
0.069s. `git diff --check` passed. Local host package sources were not changed;
actual package installation and complete qualification require the new CI run.
No service code/schema/dependency version changed, so prior 466 local service/provider
results are historical evidence, not a new full-suite pass. No deployment or billing.

Primary references checked 10 November 2026: Playwright browser installation
https://playwright.dev/python/docs/browsers and Ubuntu archive integrity
https://documentation.ubuntu.com/security/software-integrity/archive-verification/ .
Ubuntu documents the noble-security pocket at the same official HTTPS archive.
Next: inspect the new CI, fix any remaining genuine failure, then continue the real
OAuth2 Proxy/browser identity qualification. No active local implementation remains.

### CI recovery verified — 10 November 2026

Run https://github.com/EnigmaThe1/OmniXat/actions/runs/42766550297 for 4e485e6
completed successfully: 48 core + 21 identity + 392 PostgreSQL/HTTP + 5 actual
Keycloak + 13 customer Chromium + 20 unchanged prototype = **499 tests passed**,
plus the customer container build. Logs were inspected. Service integration took
58.338s, actual provider 25.830s, customer browser 11.733s and prototype 3.198s.
This closes both the APT blocker and the preceding real-provider pending-CI gate.
Every retained browser test ran; no assertions or timeouts were weakened.
This evidence-only update changes no application/test/workflow code.
Next: actual OAuth2 Proxy/browser session qualification, cookie renewal/account
switch/logout and provider key/session revocation, then scanner/draft review.
No deployment, payment activation or statutory action. No active local task remains.

## Real provider browser sign-in — in progress (10 November 2026)

Recovered clean 38ba6ef; latest verify succeeded, no other checkout/active task.
Scope: real Chromium against disposable Keycloak over loopback TLS, with an exact
fixture certificate SPKI exception (not blanket ignore_https_errors), actual login
form/password rejection and code/nonce/token validation. Retain all prior tests.
This is provider-browser qualification, not OAuth2 Proxy cookie/session acceptance.
No production dependency/authentication, public realm, billing or filing change.

Implemented two separate real-provider Chromium cases and a reusable validated
code/nonce completion helper in the disposable fixture. Only the fixed fictional
callback page is intercepted; login form/network, credentials, codes and tokens are
real within the ephemeral test realm. Certificate exceptions match only the generated
fixture SPKI. No production authentication code or existing assertion was relaxed.
CI runs the new suite after the existing five native provider cases.

Local verification: Python compilation of both changed/new Python files, workflow
YAML parse, `git diff --check`, and 48 core tests passed (0.055s). Actual new provider
browser execution awaits CI: this environment lacks the installed Keycloak archive
and its Chromium host previously disallowed Unix sockets. No new browser pass or
full-suite total is claimed before CI. Historical latest remote verify succeeded.
Next: inspect new provider-browser CI and fix real failures, then implement actual
OAuth2 Proxy/browser cookie renewal/logout acceptance. The callback interception is
explicitly a fixture and does not qualify the gateway. No deployment/billing/filing.

### Provider-browser fixture correction

1086220 CI run 42772376140 passed 461 services, five actual-provider tests and all
20 unchanged prototype tests. Both new browser cases failed: the successful login
redirect reached a browser error page because the fictional callback is not a
real host, and the wrong-password page used a different error element ID. The
negative case's accessibility snapshot showed the actual rejection message.
The fixture now captures the actual callback navigation request and forces the
fictional callback hostname unresolvable, preventing external code disclosure
without requiring a fake successful callback document. It checks the exact rejection
text instead of the obsolete element ID. State/issuer/code/nonce/token/replay checks
remain, and no authentication or test timeout is relaxed. Inspect follow-up CI.

### Provider-browser verified checkpoint — 10 November 2026

Commit `4ac9eb857a2754af7817d45a3f848ce3b70e0c4e` passed GitHub Actions
[run 42773047157](https://github.com/EnigmaThe1/OmniXat/actions/runs/42773047157).
The job logs report **501 tests passed**: 48 core (0.110s), 21 identity (0.208s),
392 PostgreSQL integration (60.067s), five actual Keycloak HTTP/service (25.260s),
two actual Keycloak Chromium (22.131s), 13 customer Chromium (11.607s), and all
20 retained fictional-demo tests including browser approval (3.241s). The customer
container build also passed. This supersedes the pending-CI notes above. The initial
browser fixture failures remain recorded for recovery; neither test was removed,
skipped, weakened or given a longer timeout to obtain this result.

The implemented increment qualifies real provider form login, wrong-password
rejection, callback state/issuer, S256 code exchange, ID-token nonce/signature,
strict access-token verification and single-use code handling. It does not qualify
OAuth2 Proxy cookies, renewal, account switch/logout, MFA/recovery or production
operation. Next resumable increment: run the maintained gateway against the same
disposable provider and customer app, then verify actual browser session issuance,
renewal and logout through shared services. No active writer remains after this
checkpoint; no deployment, paid activation, private records or statutory action.

## Actual gateway browser sessions — in progress (10 November 2026)

Recovered clean ed78024 from the connected remote; latest verify passed, no
commercial PR or other checkout/task writer. Scope: checksum-pinned OAuth2 Proxy
7.15.6 (official release checked today) using the existing customer config template,
disposable Keycloak, actual customer ASGI/PostgreSQL services and real Chromium.
Qualify HTTPS-only host cookies, forwarded access tokens, refresh, local sign-out,
spoofed headers and persisted membership revocation. No live realm or deployment.
Provider logout/MFA/recovery and production operation remain separate gates.
Local socket binding is denied by this host; actual network/browser qualification
must run on CI. Retain all existing suites and report their actual results.

Implemented explicit gateway/ASGI loopback fixtures and two real-browser journeys,
using the existing template and a checksum-pinned official download. Generated
email claims exist only in the disposable provider profile. Token observation stores
digests plus verified metadata; no credentials/logs/screenshots are uploaded.
Local checks: 48 core tests passed (0.094s), 21 identity tests passed (0.299s), Python
compilation and installer shell syntax passed; official binary version verified.
Local socket denial prevents PostgreSQL/browser execution. Full CI is required; no
new gateway pass is claimed yet. Resume from CI and fix actual failures without
skipping retained browser tests. No deployment, billing or statutory action.

### Gateway fixture recovery

5b8f7e8 run 42780334595 passed all 461 services, five provider HTTP cases, two
provider Chromium cases and 20 retained prototype tests. New gateway cases failed:
HTTP upstream was rejected by the unchanged HTTPS-required app boundary, then the
next case hit a fixture identity uniqueness conflict. Customer Chromium/container
steps did not run. The fixture now uses real upstream TLS with the generated root
explicitly installed through Go SSL_CERT_FILE and restores the identity after each
case. Landing status/heading checks fail promptly on transport errors. No HTTPS,
issuer, nonce, email, header or database authority validation was relaxed. Also
corrected the operator template refresh from five minutes to one minute, below
the fixture provider's three-minute access-token life. Follow-up CI is required.

50fec20 run 42781089316 passed the real gateway login, attributed record creation,
actual refreshed-token replacement and local sign-out journey. The other test
stopped at a negative-fixture assertion: malformed state is rejected with 500 by
the maintained gateway before its CSRF branch. Use an actual gateway-generated
state, remove the issued CSRF cookie, then require exactly 403 and no session.
This exercises the intended missing-cookie rejection without accepting 500.
All prior services/provider/prototype cases passed again; full follow-up CI remains
required. Checked the pinned gateway's OAuthCallback implementation for this path.

### Actual gateway verified checkpoint — 10 November 2026

`84f6142e7bd5608a8393469c53aa0358724f4b50` passed
[GitHub Actions run 42781825221](https://github.com/EnigmaThe1/OmniXat/actions/runs/42781825221).
Logs report **503 tests passed**: 48 core (0.090s), 21 identity (0.475s), 392
PostgreSQL integration (73.381s), five native Keycloak (30.743s), two provider
Chromium (29.789s), two actual gateway Chromium (38.882s), 13 customer Chromium
(15.379s) and all 20 unchanged prototype tests including browser approval (3.698s).
The customer container build passed. Python compilation, installer shell syntax,
workflow YAML and diff checks passed locally; local socket binding remains host
blocked. CI supplies the actual network/browser evidence. No tests were removed,
skipped or given longer timeouts to obtain the passing result.

The gateway now has demonstrated form/PKCE sign-in, secure host cookie issuance,
attributed record writes, actual refreshed access-token forwarding and local
cookie sign-out through the real TLS app/provider and PostgreSQL. It rejects
unauthenticated spoofing and a genuine-state callback without its CSRF cookie;
authenticated spoofed token headers cannot replace identity, and persisted viewer
and revoked memberships still deny access. The template refresh interval is now
one minute rather than five, below the qualified three-minute access-token life.

This supersedes the pending-CI notes above. The documentation follow-up changes
no runtime/test/workflow files. Next resumable increment: qualify new-tab pending
save/upload recovery and account switching through this actual gateway/provider
rather than the existing stand-in, then continue authorised scanner/draft-review
customer journeys. Provider-wide logout, stolen-cookie/server-side revocation,
concurrent refresh, MFA/recovery, key rotation and production restore/security
qualification remain open. No production readiness, payment, contract, deployment
or statutory transport claim. No active implementation remains after publication.

## Actual gateway pending-work recovery — in progress (10 November 2026)

Recovered clean 9dd7ed4; current remote check passed, no other checkout/writer or
commercial-head PR. Scope: real gateway/provider new-tab reauthentication for an
unsaved organisation and selected evidence file, plus retry denial after a second
real account signs in, followed by recovery under the initiating account. Use the
existing permission, expected-actor and quarantine services; no fabricated tokens
or intercepted protocol responses. Add only fictional generated provider accounts
and opt-in evidence scopes/grants to the isolated fixture. Retain every prior suite.
Local network/browser execution may remain host-blocked; CI evidence is required.
No deployment, paid activation, contracts or statutory action.

Implemented three actual recovery cases plus shared fixture reuse. A separate
opt-in recovery realm profile creates a generated second account and optional
evidence scopes; the existing constrained evidence grants/spool are reused. The
cases require preserved inputs/file digest, real SSO recovery in an opener-free tab,
no duplicate original, wrong-actor retry 409 and one note after correct-account
recovery. Provider cookie removal forces real password entry only in the switching
fixture; provider logout/revocation is not claimed. No production code/dependency,
permission or authentication rule changed. Local 48 core (0.045s) and 21 identity
(0.252s) tests passed; five gateway cases collect (two retained plus three new).
Compilation/diff checks pass. TCP loopback binding passed locally, but actual Chromium launch failed with
process_singleton_posix socket Operation not permitted; PostgreSQL is absent.
Actual new browser results require full CI. Resume there, fixing failures without skipping old suites.

### Customer account correction after real recovery proof

2e3cbc8 passed run 42787860362: all 506 tests and container build. Its switching
fixture removed provider cookies to force the form, which does not show how a
customer can correct a silently reused SSO account. The operator gateway template
now requests standard OIDC prompt=login for explicit login/recovery; cookie sessions
and refresh are unchanged. Recovery tests retain provider cookies and require the
real login form, switching to the second account and back using only credentials
and the existing recovery link. No browser-cookie clearing, protocol interception
or fabricated tokens remain in the new tests. Follow-up CI is required for this
configuration change; provider logout/MFA/session revocation are still not claimed.

ef40e80 run 42788896566 retained passing services/native provider/provider browser
and original two gateway/prototype cases. Three recovery cases reached the real
Keycloak reauthentication page but failed looking for an editable username; its
accessibility snapshot shows a locked previous username and Restart login button.
Tests now exercise that actual provider control before entering the account, with
provider cookies retained. Pending-work UI copy explains the account-change/restart
option. No auth rule or assertion is removed, no timeout is extended; follow-up
CI must prove complete recovery and account correction.

Account-correction acceptance also retains the wrong user's still-valid gateway
cookie for the final recovery link: no second manual local sign-out is performed
before restoring the initiating account. This proves the existing link can start
fresh login directly from an authenticated wrong-account session. No runtime rule
is changed by this final test strengthening; follow-up CI remains required.

### Verified pending-work/account-correction checkpoint — 10 November 2026

`558bb37d0374dcfdee7f528cdafccdb7c9b6e272` passed
[GitHub Actions run 42790308992](https://github.com/EnigmaThe1/OmniXat/actions/runs/42790308992).
Logs report **506 tests passed**: 48 core (0.094s), 21 identity (0.257s), 392
PostgreSQL integration (68.055s), five native provider (34.206s), two provider
Chromium (30.491s), five gateway Chromium (79.006s), 13 customer Chromium
(15.416s), and all 20 retained prototype cases including browser approval (3.509s).
The customer container build passed. No test was removed, skipped or given a longer
timeout to obtain this result. Local 48 core/21 identity tests, Python compilation,
JavaScript syntax, TOML parsing and diff checks passed. TCP binding is available,
but local Chromium cannot create its process-singleton Unix socket and PostgreSQL
is absent; CI supplies actual browser/database evidence.

This closes the pending follow-up above. The final code requests prompt=login on
explicit sign-in/recovery, uses Keycloak's actual Restart login control to correct
an account and preserves the original tab's organisation input/selected file.
Actual file digest, single quarantined original, wrong-actor 409 and one correctly
attributed note are verified. Direct correction retains the wrong account's valid
gateway/provider cookies and uses the existing recovery link without a second
manual local sign-out. No cookies are edited, no tokens fabricated and no protocol
response intercepted in the final recovery cases. Background refresh and all prior
authority checks still pass. The pending-work message explains the provider's
account-change/restart option.

Next concrete increment: authorised scanning/status and draft review through the
customer website using the existing evidence/quarantine services and a qualified
trusted scanner adapter. Uploaded evidence remains quarantined; no clean verdict,
extraction or accounting entry is implied by upload. Production MFA/account recovery,
provider-wide logout, stolen-cookie/server-side revocation, key rotation, concurrent
refresh and restoration/security qualification remain open. The final follow-up is
documentation only. No active implementation remains after publication; no deployment,
paid activation, contract, private records or statutory action occurred.

## Trusted scanner and customer scan status — in progress (10 November 2026)

Recovered clean a3999b5. Its latest run 42791352363 passed all 506 tests but
container pip download failed with BrokenPipeError; keep that failure distinct
from the preceding passing build. No other writer/checkout or commercial-head PR.
Scope: bounded private-socket ClamAV INSTREAM adapter and explicit trusted worker,
real daemon qualification using harmless custom test signatures, plus execute-only
tenant/identity-scoped status API and customer UI. Reuse quarantine/scan claims and
active-policy rules; no customer verdict, scanner selection, payload download or
scan/claim mutation privilege on the web process. No automated customer request
queue, extraction or ledger effects in this increment. Real malware/signature
coverage and production scanner configuration still require qualification.

Implemented the private-socket adapter/explicit worker, migration 0064 metadata
capability, opt-in same-origin GET route, server DSN configuration and refreshable
customer status panels. New checks: eight offline protocol cases; seven PostgreSQL
status/privilege cases (including forced-RLS non-bypass function owner); two status
Chromium cases; three actual ClamAV/worker/status qualification cases. CI retains
all old suites and installs the official daemon for a harmless synthetic-rule test.
Local 56 core tests passed (0.057s), 21 identity tests passed (0.346s), compilation,
JavaScript syntax, test discovery and diff checks passed. PostgreSQL/ClamAV are not
installed here and local Chromium remains host-restricted; new integration/browser
passes and the container retry await CI. See commercial/SCANNING.md for exact
configuration, grants, trust boundary and open production gates. No real records,
payment activation, deployment, contracts or statutory action.

### Scanner/status CI follow-up

2ba2ce0 run 42797784802 passed 56 core, 21 identity, 399 PostgreSQL tests, all
provider/gateway cases, all three real ClamAV cases and the retained prototype.
Observed official package: clamav-daemon 1.5.4+dfsg-0ubuntu0.24.04.1. The daemon
fixture uses only its private synthetic NDB rule, not the installed official DB.
One customer Chromium case errored after successfully hiding expired-session
content: its role locator excluded the now-hidden status region before checking
empty text. The locator now includes hidden regions so the security assertion
still requires empty DOM content. No production code, auth rule or timeout is
changed; no test skipped. Container build did not run after this error. Inspect
follow-up full CI and build before claiming completion.

### Scanner/status verified checkpoint — 10 November 2026

Code 029189b29a9f0ed470517455f8f5d9b019a1da41 passed the complete commercial
workflow run 42798834630 (job 129770822486): 526 tests, zero failures/errors/skips,
and the customer container build. Exact suite results: 56 core (0.126s),
21 identity (0.314s), 399 PostgreSQL (72.733s), five native Keycloak (37.178s),
two provider Chromium (32.996s), five gateway Chromium (82.995s), three actual
ClamAV worker/status qualification (1.934s), 15 customer Chromium (18.965s), and
all 20 retained fictional-demo tests including browser approval (3.966s).
This supersedes the pending and failed-run notes above. The hidden-region
locator correction preserves the empty-DOM session-expiry assertion.

Qualification used Ubuntu clamav-daemon 1.5.4+dfsg-0ubuntu0.24.04.1 and a private
synthetic NDB rule only. It proves real protocol/worker/persistence/status/UI
behaviour, not production malware coverage. Scanner-browser qualification uses
the existing gateway stand-in; separate real provider/gateway suites also pass.
Production requires qualified immutable scanner configuration/signature policy,
protected socket/credentials and operational security/restore validation.
Uploads remain quarantined; no automatic scan, extraction, ledger entry or final
approval is implied. Scan status is point-in-time and must be rechecked by any
future extraction gate. No customer original is exposed through the status API.

Next resumable scope: durable authorised customer scan requests through shared
services (permissions, policy validation, retry/idempotency and tenant isolation),
then qualified extraction and human draft review. See commercial/SCANNING.md for
configuration, grants and limits. This follow-up changes documentation only.
Fetch/check branch, working tree, remote movement and checks before resuming.
No active writer remains after publication. No deployment, billing activation,
paid contract, private records or statutory submission occurred.

## Durable customer scan requests — in progress (10 November 2026)

Recovered clean b3220ff and its passing run 42799836148; one checkout/writer, no
commercial-head PR or unfinished local task. Scope: opt-in, execute-only request
capability, tenant-scoped durable receipt per evidence/current operator policy,
fresh human editor/owner and evidence:scan authority, strict POST and customer UI.
Retries deduplicate; users cannot pick a scanner/policy or mutate verdicts. Add an
explicit worker request mode; no automatic daemon, extraction or ledger effects.
Production scanner qualification remains open.

## Durable scan-request implementation checkpoint — 10 November 2026

Implemented migration 0065 and shared request service, strict opt-in POST,
separate execute-only request DSN/capability, customer Request scan UI, requested
status and explicit worker --requested admission. Natural tenant/evidence/policy
idempotency preserves the first receipt/actor, including four concurrent requests.
No client policy, verdict, original download or auto-started scanner. New scope:
evidence:scan plus records:read/write and evidence:read; only current human
owner/editor memberships qualify. The worker checks current policy and requester
revocation/disable/role/token-cutoff before the bounded existing scanner operation.
Read-only status and request credentials stay separate from scanner credentials.

Local verification: 56 core tests passed (0.154s), 21 identity (0.510s), all 408
PostgreSQL integration tests (75.210s) on disposable PostgreSQL 16.2/psycopg 3.3.8,
including nine new request tests, a non-bypass migration owner, tenant isolation,
concurrency, strict transport, grants, actor continuity and revocation/cutoff.
Python compilation, JavaScript syntax and git diff --check passed. An initial
non-bypass test exposed SELECT row locks requiring authority beyond the existing
RLS policies; request admission now uses the established fresh lookup and locks
only the active policy. No identity RLS policy was widened. Member authority is
not continuously locked; the worker independently rechecks it before processing.
Local Chromium download returned invalid/truncated ZIPs; no local browser pass is
claimed. Two new browser cases and the strengthened actual-daemon worker test
await full CI; all prior suites and container/prototype checks remain intact.

Read commercial/SCANNING.md for setup, grants and explicit limits. Requests do not
start an automatic processor. Historical request status is not proof that its
requester remains authorised. Same-policy first-request cancellation/re-authorisation
and bounded dispatch/retry remain the next resumable step, then qualified extraction
and human draft review. Scanner qualification uses synthetic rules; production
malware coverage/configuration/security/restore remain open. Nothing deployed,
billed, contracted, privately disclosed or submitted to an authority.

### Request-browser CI follow-up

b200b24 run 42804900353 passed core/identity/all 408 PostgreSQL tests, actual
provider/gateway and ClamAV suites, 16 of 17 customer browser cases and all 20
retained prototype cases. One new browser case revoked the member immediately
after starting asynchronous status lookup, before Request scan rendered; it then
timed out looking for the button. Added an explicit visible-button barrier before
revoking authority so the case tests denial from a previously authorised screen.
No production code, timeout, permission or security assertion changed. Container
build was skipped after that browser error. Full follow-up CI is still required.

### Verified durable request checkpoint — 10 November 2026

Code ca0ca5e270636c976ee0c8b1fce39b297d034160 passed the full commercial workflow
run 42805866972, job 129794700680: **537 tests**, zero failures/errors/skips and
customer container build. Exact suites: 56 core (0.310s), 21 identity (0.317s),
408 PostgreSQL (66.135s), five native Keycloak (28.873s), two provider Chromium
(24.811s), five gateway Chromium (65.063s), three real ClamAV worker/status
qualification (1.460s), 17 customer Chromium (17.530s), and all 20 retained
prototype tests including browser approval (3.233s). This supersedes pending/failure
notes above. Both new request UI cases pass: persisted status across reload and
fresh rejection after revocation from a previously authorised screen. The actual
daemon test processes an API-created request through explicit --requested worker
admission, stores its verdict and displays the result in Chromium. Browser request
tests use the existing server-side gateway stand-in; independent real provider and
gateway suites also pass. The final synchronization fix changes no runtime rule.

Observed daemon package remains 1.5.4+dfsg-0ubuntu0.24.04.1; qualification uses only
private synthetic signatures and fictional records, not production malware coverage.
No automatic processor, same-policy request cancellation/re-authorisation or
continuous in-flight cancellation is implemented. Next: complete that customer
request lifecycle and bounded dispatch/retry, then qualified extraction/human draft
review through shared services. Read commercial/SCANNING.md for exact grants,
configuration and limits. Production scanner/security/restore qualification remains
open. This final follow-up changes documentation only; runtime matches the passing
CI revision. No active writer remains after publication. Fetch and inspect current
remote/checks before resuming. No deployment, billing activation, contract, private
record publication or statutory submission occurred.

## Scanner configuration file boundary — in progress (10 November 2026)

Recovered clean 3568290; no active local work or commercial-head PR. Before queue
dispatch, fix the worker lstat/open race: open without symlink following or blocking,
validate the opened descriptor, bound decoding/reads and reject empty configuration.
No SQL, policy, UI, dependency or filing behaviour changes.

## Scanner configuration descriptor validation — 10 November 2026

Fixed the explicit worker's lstat/open race with a shared stdlib-only private-file
reader. It opens O_NOFOLLOW/O_NONBLOCK/O_CLOEXEC, validates fstat ownership/type/
permissions on that exact descriptor, bounds reads to 65537 bytes, rejects blank
or malformed UTF-8 and closes the descriptor on failure. Seven new tests cover
size boundaries, permissions/owner, symlink, FIFO/directory, pathname replacement
and cleanup. All 63 offline core tests passed locally (0.652s); compilation and
diff checks passed. No database/UI/prototype source changed; full browser/daemon/
container qualification remains pending CI for this revision, with all suites
retained. Python os documentation checked 10 November 2026:
https://docs.python.org/3/library/os.html#os.open

This closes one worker configuration qualification gap, not production scanner
qualification. Ancestor directories and concurrent writes to the same inode must
still be operator-controlled. Next: request cancellation/re-authorisation and
bounded dispatch, then qualified extraction/human review. No active writer remains
after publication. No deployment, payment, contract, private records or filing.

## Bounded requested-scan dispatch — in progress (10 November 2026)

Recovered clean 9e5107c; its full CI run 42831147525 passed. No active writer or
commercial-head PR. Add explicit private-manifest dispatch of at most five items
within one tenant/organisation, validating all IDs first, fresh worker admission
per item, fail-fast and durable receipt reuse. No daemon, queue enumeration, SQL
changes, extraction or ledger work. Cancellation/re-authorisation remains open.

## Bounded requested-scan dispatch checkpoint — 10 November 2026

Added explicit --batch-file worker mode: private operator manifest, one to five
distinct canonical evidence UUIDs, fixed tenant/organisation, full ID validation
before work and mandatory fresh current-request admission for every item. It
emits each committed receipt, stops on the first failure, and retries reuse durable
verdicts from the completed prefix. No background service or automatic retry starts.
Cancellation/re-authorisation, queue enumeration, extraction and ledger remain open.

Local validation: 66 core tests (0.059s), 21 identity (0.294s), and all 411 PostgreSQL
integration tests (48.470s) passed on disposable PostgreSQL 16.2. Three new core
cases cover strict manifests; three new PostgreSQL cases cover partial failure/
retry, revocation between items and validation/admission before scanning. Compilation
and diff checks passed. Existing real-daemon qualification now exercises the batch
CLI with a private single-item manifest; full browser/daemon/container CI for this
revision remains pending. No test was skipped or removed. The preceding 9e5107c
run 42831147525 passed all 544 tests and container build, closing its pending note.

See commercial/SCANNING.md for invocation and limits. The five-item cap is not an
overall wall-clock SLA; per-service timeouts apply. Production scanner qualification
still uses synthetic rules only. Next: customer cancellation/re-authorisation, then
qualified extraction and human draft review. No active writer remains after
publication; no deployment, payment, contract, private records or statutory action.

## Customer scan cancellation — in progress (10 November 2026)

Recovered clean 9fef785; full batch CI 42840571777 passed. One writer, no active
commercial-head PR. Add current-policy cancellation with retained attribution,
separate execute grant, strict POST and customer UI. Block future requested-worker
admission; do not claim in-flight cancellation or erase observations/originals.
Re-authorisation remains a subsequent lifecycle increment.

## Customer scan cancellation checkpoint — 10 November 2026

Implemented migration 0066, separately granted cancel_scan capability, shared
service/strict same-origin POST and customer Cancel scan request action. Retains
original requester and first cancellation attribution/time. Idempotent concurrent
cancellation blocks future requested/batch worker admission; existing verdicts,
claims and originals are preserved. Status prefers observed blocked/scanning/scanned
states before cancelled. Current human owner/editor/scopes and optional initiating
actor are rechecked. No direct table mutation grant or scanner credential on web.

Local verification: 66 core tests (0.102s), 21 identity (0.360s), all 415 PostgreSQL
integration tests (65.679s) on disposable PostgreSQL 16.2 passed, including four
new cancellation cases and strengthened non-BYPASSRLS function-owner coverage.
Python compilation, JavaScript syntax and git diff --check passed. Local Chromium
executable is absent; the new request/cancel/reload/worker-denial browser test and
retained daemon/browser/container/prototype suites await CI. No test removed or
skipped. Prior batch revision 9fef785 full run 42840571777 passed.

Read commercial/SCANNING.md for migration/grant and exact API/behaviour limits.
Cancellation cannot interrupt an already admitted scan or override operator single-
item work. Normal request retries cannot re-authorise a cancelled same-policy
request. Next: explicit re-authorisation with preserved history, then qualified
extraction and human draft review. Production scanner/security/restore gates remain
open; no automatic processing, deployment, billing, contract, private data or filing.
No active writer remains after publication; fetch/check remote before resuming.

## Explicit scan re-authorisation — in progress (10 November 2026)

Recovered clean 7a64663; cancellation CI 42850504629 passed. Add a cancellation-
bound action with immutable prior-request history, fresh authority and idempotent
concurrent retries; stale retries must not undo a later cancellation. Connect UI,
strict POST and shared service. No automatic processor, extraction or filing.

## Scan re-authorisation checkpoint — 10 November 2026

Added migration 0067, tenant-forced-RLS history snapshots, separately granted
reauthorise_scan capability, shared cancellation-bound service/POST and Request
scan again UI. Re-authorisation requires the exact aware cancellation timestamp
returned by status; it rechecks human authority, locks the request and preserves
its entire previous request/cancellation snapshot before renewing authority.
Concurrent retries return one receipt; stale retries cannot undo a later cancel.
Status uses recorded_at as the cancellation time only for cancelled state and UI
labels it Cancelled. New grant/setup/API details are in commercial/SCANNING.md.

Local validation: 66 core tests (0.073s), 21 identity (0.365s), and all 418 PostgreSQL
integration tests (52.302s) passed on disposable PostgreSQL 16.2. Three new cases
cover history/retry/re-cancellation, concurrent renewal and strict timestamp/scope/
role rejection. Non-bypass function-owner coverage includes cancel then re-authorise
and worker admission. Python compilation, JavaScript syntax and diff checks passed.
Targeted status/re-authorisation cases were rerun after final status/error-copy
changes. The new real Chromium lifecycle case and retained full CI suites remain
pending for this revision; no test removed or skipped. Previous cancellation run
42850504629 passed, closing its pending note.

Normal request retries cannot renew cancelled work; only the explicit action does.
Existing verdicts are retained/reused rather than forcing a rescan. This is not
filing approval or automatic scanning. Cancellation still cannot interrupt already
admitted work. Next: qualify extraction and human draft review through the existing
evidence gate/shared services. Production scanner/security/restore gates remain
open. No active writer after publication; fetch/check remote before resuming.
No deployment, billing, contract, private record publication or statutory submission.
