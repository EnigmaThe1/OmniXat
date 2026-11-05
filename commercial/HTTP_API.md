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
internal actor. There is no list/search endpoint, ledger posting or automatic retry.
Unknown routes, including filing/approval/billing/admin paths, return 404.

POST requires application/json with identity content encoding. Only the specified
single field is accepted; unknown/duplicate keys, nonfinite numbers, wrong types,
blank text, NULs and invalid Unicode fail. Organisation names are limited to 200
characters; notes to 10,000. Actual streamed body bytes are limited to 32,768,
independent of Content-Length, and body intake has a five-second deadline.

Query parameters and `Idempotency-Key` are explicitly rejected in this slice. Record
creation is not yet idempotent. Do not automatically retry uncertain POST outcomes
or use this as an exactly-once AI ledger service. A client disconnect after commit
can leave a created record without a received response. Durable request keys, result
reconciliation and audit events are the next increment before retrying agent writes.

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
PyJWT 2.13.0 and disposable PostgreSQL 16.2. **58 integration tests** pass: 18 HTTP
cases, three time-control cases and the previous 37 database/membership cases.
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

Before production: durable idempotency/audit, rate limits/quotas, entity grants,
maintained-provider login/key lifecycle, browser sessions/CSRF/MFA, observability,
restore/security qualification and hosting configuration remain unfinished. A future
interactive approval service must remain separate from bearer record preparation.

Primary technical references checked 5 November 2026:

- [Starlette request streaming](https://www.starlette.io/requests/)
- [Starlette routing](https://www.starlette.io/routing/)
- [Starlette exception handling](https://starlette.dev/exceptions/)
- [PostgreSQL client timeouts](https://www.postgresql.org/docs/current/runtime-config-client.html)
- [Psycopg transaction handling](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
