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
