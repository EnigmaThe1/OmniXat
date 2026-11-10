# Customer website

The commercial website now serves a responsive workspace at `/app`, backed by the
same authenticated PostgreSQL services as the developer API. It discovers current
memberships, switches workspaces, lists/creates organisations, lists/adds notes and
reopens saved records. Viewer controls are read-only. Empty, loading, permission,
expiry and retry states are explicit. Lists use bounded cursor pagination; the
organisation filter applies to loaded rows and is labelled accordingly. Counts
are loaded records, not invented financial or platform metrics.

This is a real record workflow, not the old fictional household prototype. Evidence,
expense/journal review, reconciliation, subscription management, owner administration
and statutory packages still need complete customer journeys. The whole platform
is not production qualified merely because this workflow exists.

## Authentication and deployment boundary

Use a maintained OIDC gateway, such as OAuth2 Proxy, for the browser login/session
and refresh flow. The operator template is
`config/oauth2-proxy.customer.example.cfg`. Fill the environment-specific issuer,
client ID, redirect URL, approved email domains, verified TLS upstream and secret
mounts. It is intentionally not a working public deployment configuration. There
is no built-in password store, test-token login, provider contract or self-enrolment.
Provision identity/membership links through the existing trusted operator process.

Protect **every** `/app` and `/v1` request at the gateway. Only the public landing
page and two allowlisted static assets may bypass authentication. Forward the
provider **access token** in `X-Forwarded-Access-Token`; do not forward the ID token
in Authorization. The API independently verifies its pinned issuer, audience,
RS256 key, `at+jwt` profile, timestamps, lifetime and required claims, then resolves
current database membership and role. A provider's default token profile is not
assumed compatible: qualify that exact realm/client first, including required
`jti`, `client_id`, record scopes, header type, expiry, revocation and key rotation.
Email/group/role headers confer no authority. Ambiguous token headers are rejected.
The original bearer API remains available as a separate app factory.

The app does not receive the gateway's cookie secret or OIDC client secret. No
bearer token enters HTML, JavaScript, localStorage or sessionStorage. Browser API
requests are same-origin. Writes require one exact configured HTTPS Origin, reject
cross-site Fetch Metadata, and retain strict JSON/body limits. No CORS is enabled.
The gateway must strip incoming authentication headers before setting its own.
Keep the app network private behind it and validate host/TLS/proxy settings before
release; application code does not trust forwarded host/protocol headers.

## Database grants and directory

Apply the normal checksum-checked migrations, including 0063, with the separate
migration owner. Retain the existing constrained record-runtime grants from
POSTGRES.md and IDENTITY.md. Add a **separate execute-only directory login**:

```sql
GRANT USAGE ON SCHEMA omnixat_directory TO customer_directory_runtime;
GRANT EXECUTE ON FUNCTION omnixat_directory.list_workspaces(text,text,bigint,uuid,integer) TO customer_directory_runtime;
```

Alongside CONNECT, these are its only required grants. No direct omnixat schema or
table privileges are needed. The Python service rejects a directory connection
with direct schema privileges, owner or RLS-bypassing authority. This is a trusted
server capability, never customer SQL access or a model tool.

0063 adds directory SELECT policies restricted to the migration/function owner;
ordinary record-runtime policies remain tenant-scoped. Under forced RLS, the
function sees only the configured verified subject's identity/memberships and
related tenants. Its explicit query also requires matching issuer/subject, active
identity/membership and an issue time newer than the identity cutoff. A test runs
this with a non-superuser, non-bypassing migration owner. Context settings are
transaction-local and cleared before connection release. The directory returns
only workspace ID/name/role and a derived can-write flag. Permission checks still
run on each actual record operation; discovery is not continuing authority.

## Run or build

Install `requirements-web.txt`. Set these operator-owned variables; keep all
credentials outside this public repository:

| Variable | Value |
|---|---|
| `OMNIXAT_PUBLIC_ORIGIN` | Canonical `https://` hostname, without a trailing slash/port |
| `OMNIXAT_ACCESS_ISSUER` | Independently approved access-token issuer |
| `OMNIXAT_ACCESS_AUDIENCE` | Approved record API audience |
| `OMNIXAT_ACCESS_KEYS_FILE` | JSON object mapping approved key IDs to public RSA PEM strings |
| `OMNIXAT_RECORD_DSN_FILE` | Private record-runtime libpq DSN file |
| `OMNIXAT_DIRECTORY_DSN_FILE` | Private directory-runtime libpq DSN file |

DSN files must have no group/other permissions (for example 0600); mounted files
must be readable by the runtime UID. Startup fails closed for missing/invalid
configuration. The factory opens no connection/listener on import. It admits at
most 16 concurrent database leases per process, waits at most two seconds for a
slot, uses a two-second connection timeout and the existing transaction timeouts.

From `commercial/`, after configuring an isolated environment and gateway:

```bash
uvicorn omnixat_core.customer_server:create_configured_app --factory \
  --host 127.0.0.1 --port 8443 --no-proxy-headers --no-access-log \
  --limit-concurrency 64 --timeout-keep-alive 5 \
  --ssl-keyfile /run/secrets/web-key.pem --ssl-certfile /run/secrets/web-cert.pem
```

TLS remains required on the upstream ASGI scope; use a trusted upstream certificate.
`docker build -f commercial/Dockerfile.web -t omnixat-customer-web commercial`
builds the same app as UID 10001. Mount credentials and TLS material read-only;
no credentials or test data are built into the image. No container was deployed.
Image/base pinning, vulnerability review, restore rehearsal, load/security and
accessibility qualification remain release work.

## Verification and retry limits

Install `requirements-web-tests.txt` and run `python -m playwright install --with-deps
chromium` in a supported test environment. All fixtures are fictional. With a
disposable-cluster `OMNIXAT_TEST_ADMIN_DSN`, from `commercial/`:

```bash
python -m unittest discover -s tests -q
python -m unittest discover -s identity_tests -q
python -m unittest discover -s integration_tests -v
PYTHONPATH=.:integration_tests python -m unittest discover -s browser_tests -v
```

The browser suite uses real Chromium, actual ASGI routes and actual PostgreSQL
services, with a server-side generated-token gateway stand-in. It covers creation,
reload, viewer/revocation handling, desktop/mobile layout, untrusted note text,
unsaved-note navigation and a response lost after commit followed by idempotent
retry. It does **not** qualify an actual provider's login, gateway cookies, live
network/TLS or MFA. No test is skipped when a browser is missing.

A pending save keeps its original random idempotency key and exact payload in page
memory. Editing/navigation is blocked while confirmation is pending. Retry rechecks
authority and recovers the same record; it cannot duplicate that keyed creation.
Unsaved notes block switching records and trigger the native leave-page warning.
There is no background retry and no private draft/token storage in browser storage.
Closing/reloading an unconfirmed page loses its in-memory draft/key: check persisted
records before entering it again. Durable private draft/recovery UX remains to
qualify. Normal UUID cursor pages are not an immutable snapshot of concurrent writes.

CI in `.github/workflows/commercial.yml` runs the services, real-browser workflow,
container build and unchanged prototype suite on a PostgreSQL/Chromium runner. A
workflow definition is not proof of a successful run; inspect its actual checks.
The current workspace blocks Chromium Unix sockets and supplied a truncated
headless-shell download, so browser verification remains blocked locally. GitHub
run [42711977745](https://github.com/EnigmaThe1/OmniXat/actions/runs/42711977745)
for `51a1ba8` subsequently passed 440 service tests, both real Chromium customer
tests, all 20 unchanged prototype tests and the container build. The captured
desktop/mobile screenshots were inspected for readable layout and overflow. The
existing fictional-demo browser test remains intact and must also run in CI.

Primary technical sources checked 9 November 2026:
[OAuth2 Proxy configuration](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/),
[Playwright browsers](https://playwright.dev/python/docs/browsers),
[Starlette responses](https://www.starlette.dev/responses/),
[Uvicorn](https://pypi.org/project/uvicorn/0.52.1/).

## Opt-in evidence intake

Set `OMNIXAT_EVIDENCE_SPOOL_DIR` to a pre-provisioned private directory owned by
the runtime UID (mode 0700), on an unserved private volume with trusted ancestors.
The app factory accepts the equivalent `evidence_quarantine_dir` argument. Without
this option there are no evidence routes or controls. The gateway/client must be
separately qualified for `evidence:read` and `evidence:register` access-token scopes;
requesting a scope does not grant a membership or role. Record scopes are still
required. Only human owners/editors with all four read/write/register scopes may
upload; viewers with record/evidence read scopes may browse metadata. Agents cannot
upload or use token claims to change their persisted actor kind. The record-runtime
role additionally needs these constrained grants:

```sql
GRANT SELECT, INSERT ON omnixat.evidence_registrations TO customer_record_runtime;
GRANT INSERT (tenant_id, evidence_id, original_bytes) ON omnixat.evidence_quarantine TO customer_record_runtime;
GRANT SELECT (tenant_id, evidence_id, stored_at) ON omnixat.evidence_quarantine TO customer_record_runtime;
```

Do not grant SELECT on original_bytes or any UPDATE/DELETE/TRUNCATE. There is no
customer download or extraction endpoint. Existing scanner credentials remain
separate. No new database migration is required.

`GET /v1/workspaces/{tenant}/organisations/{id}/evidence` lists at most 50 scoped
registrations with ID, declared type, byte count, registration time and optional
quarantine storage time. `after` is the last UUID; `limit` is 1–50. It exposes no
originals, source names, hashes, locators or extracted figures. A registration
without a storage receipt is explicitly an incomplete upload, not a stored file.

`POST` on the same route accepts raw bytes with exactly one allowlisted Content-Type
(PDF, JPEG, PNG or CSV), identity encoding, no query parameters and no client digest
or Idempotency-Key. It enforces the actual 20 MiB limit even without Content-Length,
checks declared length, and bounds streamed body receipt to 15 seconds. There are
at most four active uploads per app/process, then 503; database admission remains
bounded separately. This is not a tenant quota or a fleet-wide storage limit.
Provider/gateway request-body buffering and size/time controls must also be qualified.

Before receiving bytes it checks current human authority and the parent. It stages
into anonymous temporary files, computes the fingerprint from bytes using the shared
intake service, registers metadata and stores through the existing write-only
quarantine service. Membership is rechecked after receiving bytes and again before
payload storage. The registry and quarantine commit separately: interruption can
leave a visible metadata registration; retrying the exact same bytes/type finishes
it and preserves the first ID/storage receipt. Same bytes with conflicting metadata
return 409. Concurrent revocation governs subsequent checks, not an already admitted
transaction. No automatic background retry occurs.

The browser keeps an uncertain upload's File and type in page memory and disables
editing/navigation until the same-file retry resolves. Reload loses that selection;
browse the stored list or reselect the same file to reconcile. No filename, token,
file bytes or draft enters local/session storage. Stored files are labelled as
quarantined; no scan, extraction, ledger posting or official approval is claimed.
Declared format is not proof of a valid file. The 20 MiB original may temporarily
occupy two private spool files and a bounded memory buffer during PostgreSQL storage.
Disk/database capacity, encryption, payload-free logs/backups, retention, tenant
quotas and a qualified scanner/processing path remain prerequisites for real use.

Technical sources checked 9 November 2026: [Starlette streaming requests](https://www.starlette.dev/requests/)
and [Python temporary-file cleanup](https://docs.python.org/3.12/library/tempfile.html).

### Inspecting an evidence receipt

With evidence intake enabled, `GET /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}`
returns one metadata receipt: `id`, `organisation_id`, declared `media_type`,
`byte_size`, lowercase hex `content_sha256`, `registered_at` and optional `stored_at`.
It requires current records/evidence read scopes and persisted membership, including
viewer access. Parent organisation and evidence must belong to the same tenant.
It rejects query parameters and Idempotency-Key; HEAD has no response body. No new
grants or migration are needed. The list endpoint remains unchanged.

The customer evidence list has an expandable receipt panel. Each opening reads
fresh metadata; closing removes the displayed fields. Loading, retry, sign-in and
access-denied states are handled without browser storage. SHA-256 is computed by
the existing intake service from original bytes, not supplied by the browser. It
identifies the registered content; it is not validation, a scan verdict or proof
of accounting/filing completion. A null storage time means registration exists but
upload storage is incomplete. Exact-file/type retry completes the existing receipt.

The endpoint serves no original bytes, filename, uploader identity, object locator,
extracted figure or processing instruction. The hash is private workspace metadata,
not a public lookup capability. Existing no-store/CSP/referrer controls apply.
Authority is resolved again before reading metadata; as elsewhere, a revocation
cannot retract an already admitted transaction. No scanning or processing is started.

## Recovering sign-in without losing pending work

The error/dialog **Sign in again** action opens a new tab using
`/oauth2/start?rd=/app/reauthenticated` with explicit `noopener noreferrer`.
The original tab keeps its File, immutable request payload and creation key in
memory. Keep it open. After the maintained gateway returns, the recovery page
checks the signed session through the existing bounded workspace directory API;
only a successful check shows instructions to return. It does not display records,
automatically retry writes or communicate with the opener. Invalid/expired sessions
show retry/sign-in controls. No token or draft is placed in URLs, browser storage,
postMessage or a broadcast channel. The fixed redirect is not caller-selectable.

The new route remains protected by the gateway's existing all-`/app` rule. Do not
add it to skip-auth routes. Gateway redirect and browser cookie renewal still need
qualification with the exact maintained provider; a passing app fixture is not
provider qualification. Returning to the original tab and explicitly retrying uses
the renewed same-origin gateway session. Closing/reloading that tab still loses
memory-only work and requires checking saved records before creating a new save.

Workspace context now includes `actor_id`, the current persisted identity UUID
(no email, external subject, token or credential). Each browser write pins that ID
with its pending payload and sends `X-OmniXAT-Expected-Actor`. The optional header
is a restriction, never an identity assertion: ordinary signature, membership,
role and scope checks run independently. Creates compare it inside the existing
record transaction; evidence checks it at admission and each persistence unit.
A mismatch returns `409 session_changed` without writing, so the browser preserves
the original request/key/File and asks for the original account. This prevents a
lost-response retry crossing the actor-scoped idempotency namespace if the user
signs in as a different account. Malformed/duplicate headers fail with 400; reads
reject the header. Existing API clients omitting it keep their current contract.
Revocation still cannot retract an already admitted transaction.

Primary technical references checked 10 November 2026:
[OAuth2 Proxy endpoints](https://oauth2-proxy.github.io/oauth2-proxy/features/endpoints/),
[login redirect integration](https://oauth2-proxy.github.io/oauth2-proxy/configuration/integrations/nginx/),
and [browser noopener behaviour](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/rel/noopener).
No dependency version or legal rule changed. Provider-wide logout is not claimed;
OAuth2 Proxy's local sign-out alone does not necessarily end the provider session.
