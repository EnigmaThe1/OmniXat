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
