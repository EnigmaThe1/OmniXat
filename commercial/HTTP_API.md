# Authenticated record API — C2 first slice

This is a development ASGI application factory. Importing it starts no server and
opens no network listener. It provides organisation/note preparation only. Browser
login, billing, bank feeds, filing, approvals and owner administration remain separate
unfinished services. No deployment or production qualification is implied.

## Constructing the application

Install `requirements-http.txt`. Supply `create_app(verifier=..., connection_factory=...,
allowed_hosts=[...])` from `omnixat_core.http_api` with trusted server configuration:

- The pinned [access-token verifier](IDENTITY.md), with no request-controlled keys.
- A context manager factory that exclusively leases an idle autocommit psycopg
  connection using the constrained runtime role. It must bound connection acquisition
  and network waits; tests use `connect_timeout=2`. Never return a shared connection
  or the migration owner. The application exits the context before sending success.
- Explicit DNS/IPv4 hostnames. Empty lists, wildcard hosts and URLs are refused.

The ASGI scope must report HTTPS. The app ignores forwarded-protocol/host headers;
proxy trust and TLS termination must be configured separately and narrowly at the
server boundary. There is no HTTP redirect, CORS enablement or cookie authentication.
Only one `Authorization: Bearer <access-token>` header is accepted. Token validity is
checked before body processing/database acquisition and again at the service boundary.
Membership, role, actor type and revocation resolve from PostgreSQL on each operation.
Caller role/tenant/MFA headers cannot grant authority.

## Current routes

All route identifiers are UUIDs. The requested workspace must be an active persisted
membership. Object IDs belonging to other workspaces return the same not-found error
as nonexistent IDs when the caller has membership in the requested workspace.

| Method | Route | Request JSON | Shared service |
|---|---|---|---|
| POST | `/v1/workspaces/{tenant}/organisations` | `{"display_name":"Fictional organisation"}` | Create organisation |
| GET | `/v1/workspaces/{tenant}/organisations/{id}` | None | Read organisation |
| POST | `/v1/workspaces/{tenant}/organisations/{id}/notes` | `{"body":"Fictional note"}` | Create attributed note |
| GET | `/v1/workspaces/{tenant}/notes/{id}` | None | Read note |

POST returns 201; reads return 200. Responses contain `data` and a generated
`request_id`. IDs are JSON strings. Creation attribution comes from the verified
internal actor. Cursor-paginated lists and workspace context are now available (see below); ledger posting and automatic retry are absent.
Unknown routes, including filing/approval/billing/admin paths, return 404.

POST requires application/json with identity content encoding. Only the specified
single field is accepted; unknown/duplicate keys, nonfinite numbers, wrong types,
blank text, NULs and invalid Unicode fail. Organisation names are limited to 200
characters; notes to 10,000. Actual streamed body bytes are limited to 32,768,
independent of Content-Length, and body intake has a five-second deadline.

## Safe retries for creation

A POST may carry one `Idempotency-Key` header (1–128 ASCII letters, digits,
periods, underscores, tildes or hyphens). Use a random opaque key, never a credential
or record value. Repeat the same key and the same validated input when reconciling
an uncertain POST outcome. The workspace, authenticated actor and operation define
the key's scope. For notes the parent organisation and exact text are bound; the
parent must still be accessible. JSON formatting does not affect the input digest.
A matching retry returns 201 with the same record and a new request ID. Reuse with
different valid inputs returns 409 `idempotency_conflict`. Membership, revocation
and scopes are checked before replay. GET does not accept this header. Query
parameters remain unsupported on creation and single-object routes.

Migration 0003 adds a creation receipt for each successful shared-service creation.
The receipt and record commit together; it stores workspace, actor, operation,
result ID, timestamp and, for keyed requests, digests. It stores no raw key, request
body, token or response copy. Digests are private metadata, not anonymised data.
No-key requests remain distinct writes. There is no automatic retry or receipt
expiry; a concurrent request that hits the database wait limit can retry with the
same key. This contract covers these two database writes only, not ledger posting
or external side effects. Audit access and retention rules still need qualification.

## Errors and resource controls

Errors expose only an error code and generated request ID. No raw token, SQL, body,
connection string, provider diagnostic or traceback is returned. Responses use
no-store/no-cache and nosniff headers. Caller-provided request IDs are not trusted.

| Status | Meaning |
|---|---|
| 400 | Invalid host/TLS, identifier, JSON/header or unsupported parameter |
| 401 | Missing/invalid bearer token before work; Bearer challenge supplied |
| 403 | Membership/current service authority or scope denied |
| 404 | Object or route not found |
| 405 | Method not allowed |
| 408 | Body intake timed out |
| 409 | Creation key reused with different valid inputs |
| 413 | Body too large |
| 415 | Unsupported media type or content encoding |
| 422 | Field validation failed |
| 503 | Database operational failure or transaction deadline |
| 500 | Unexpected internal failure, with generic response |

Shared record transactions now set local statement (5s), lock (1s) and idle-in-
transaction (5s) timeouts. A monotonic elapsed-time check refuses to commit work
exceeding ten seconds, causing rollback. These are per-statement/idle controls plus
a pre-commit deadline, not a hard ten-second process-cancellation guarantee or a
server-wide request deadline. PostgreSQL 16 lacks the later transaction_timeout
setting. Bound connection/pool/thread admission and server/network timeouts at the
hosting layer before release; this slice supplies no production server configuration.

## Verification and remaining scope

On 5 November 2026: Python 3.12, Starlette 1.6.0, httpx 0.28.1, psycopg 3.3.8,
PyJWT 2.13.0 and disposable PostgreSQL 16.2. **68 integration tests** pass, including concurrent replay, rollback,
scoping, audit grants and HTTP conflict/validation/revocation checks.
The 32 core and nine token-verification tests also pass. ASGI TestClient is not a
real network/TLS deployment test. Its httpx compatibility path emits a deprecation
warning recommending httpx2; no warning was suppressed or test skipped.

```bash
cd commercial
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s identity_tests -v
python3 -m unittest discover -s integration_tests -v
```

Integration needs `OMNIXAT_TEST_ADMIN_DSN` for the disposable cluster described in
[POSTGRES.md](POSTGRES.md). Tests use generated fictional identities/tokens and
separate constrained database logins. No real customer data is required.

Before production: audit access/retention, rate limits/quotas, entity grants,
maintained-provider login/key lifecycle, browser sessions/CSRF/MFA, observability,
restore/security qualification and hosting configuration remain unfinished. A future
interactive approval service must remain separate from bearer record preparation.

Primary technical references checked 5 November 2026:

- [Starlette request streaming](https://www.starlette.io/requests/)
- [Starlette routing](https://www.starlette.io/routing/)
- [Starlette exception handling](https://starlette.dev/exceptions/)
- [PostgreSQL client timeouts](https://www.postgresql.org/docs/current/runtime-config-client.html)
- [Psycopg transaction handling](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)


## Customer website list/context extension

The [customer website](CUSTOMER_WEB.md) uses these additional read routes through
the same signed identity/membership services:

| Route | Result |
|---|---|
| `GET /v1/workspaces` | Current subject's active memberships, name, role and can-write flag; opt-in separate execute-only directory factory |
| `GET /v1/workspaces/{tenant}/context` | Current workspace name/role and can-write flag |
| `GET /v1/workspaces/{tenant}/organisations` | Organisation IDs, names and creation timestamps |
| `GET /v1/workspaces/{tenant}/organisations/{id}/notes` | Parent-scoped note IDs, text and creation timestamps |

Lists return `data.items` and `data.next_cursor` (null on the final page). Optional
`limit` is a decimal integer 1–50 (default 50); `after` is the canonical lower-case
UUID cursor from the previous page. Duplicate/unknown parameters and malformed
cursors/limits fail. Ordering is by immutable UUID, not a concurrent snapshot.
Notes validate the parent under the requested tenant, including empty lists.
Revocation/scopes are checked on each call. Context is advisory UI metadata, never
permission to skip a write check. `create_app` takes an optional separate
`directory_connection_factory`; without it the global directory route is absent.
The bearer-only factory itself gains no cookie authentication or CORS.
