# Staff browser qualification app

`create_staff_browser_app` is an opt-in ASGI factory for testing staff identity
against an isolated Keycloak realm with fictional accounts. It is not mounted
by the customer app, does not start a listener, and has no owner or tenant routes.

Configure the exact lowercase HTTPS origin and a trusted `KeycloakStaffLogin`
whose registered redirect URI is that origin plus `/staff/login/callback`.
Pass three independent context-manager factories for exclusive autocommit
attempt, session and directory connections. The hosting layer must ensure the
ASGI scheme reflects trusted TLS termination; the app does not interpret
forwarded headers. Set bounded connection acquisition and request deadlines.

| Route | Behavior |
| --- | --- |
| POST /staff/login | Requires the exact Origin and admission; sets a short browser binding cookie and redirects to the pinned provider. |
| GET /staff/login/callback | Validates callback parameters and binding; exchanges the one-time code, sets the opaque session cookie and redirects to the fixed session check. |
| GET /staff/session | Verifies the current staff session and returns only the signed-in status. |
| POST /staff/logout | Requires the exact Origin and admission; revokes the stored session and clears browser cookies. |

For a real browser, initiate POSTs from a same-origin test form. The callback
accepts one each of code, state and issuer, plus optional Keycloak session state.
Repeated, malformed or unexpected fields and duplicate authentication cookies
are rejected. Both cookies use the `__Host-` prefix, Secure, HttpOnly,
SameSite=Lax, and no Domain attribute. The database remains authoritative for
the MFA deadline, which can precede browser cookie expiry. Responses are
non-cacheable and suppress referrers.

A trusted `admit(request, action)` function is required and only an explicit
true admits a request. Install shared rate limits at the qualification ingress
or in this hook; the factory does not supply a distributed limiter. Do not use
untrusted forwarding headers as a client identity. Disable or redact query,
cookie and redirect logging at the ingress, ASGI server and tracing layer:
response headers do not hide a callback URL from an access log.

Before any owner route, complete the isolated realm MFA/recovery test matrix,
wire rate limiting and [expiry cleanup](STAFF_AUTH_CLEANUP.md), and verify TLS,
cookie behavior and log redaction in the qualification environment. Current
tests use an in-process ASGI client and simulated provider responses, not a
browser against a real realm.

Reference: [OAuth Security BCP, credential leakage via referrers](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.2).

## Shared qualification limits

Migration 0012 adds an optional PostgreSQL implementation of the admission
hook. Pass `PostgresStaffAdmission(admission_connections, key=admission_key)`
as `admit`. Use a fourth, separate idle-autocommit connection factory with
bounded acquisition, and load a dedicated 32-byte random key from trusted
configuration. All workers serving this app must share the same key and
database. Provision only CONNECT and these object grants:

```sql
GRANT USAGE ON SCHEMA omnixat_staff_admission TO staff_admission;
GRANT EXECUTE ON FUNCTION omnixat_staff_admission.admit(text,text) TO staff_admission;
```

These qualification defaults are per fixed database minute:

| Action | Per source | Total |
| --- | ---: | ---: |
| Login | 5 | 60 |
| Callback | 10 | 120 |
| Session check | 60 | 300 |
| Logout | 10 | 60 |

Source is the trusted ASGI client IP (IPv4 or IPv6 /64, with IPv4-mapped IPv6
normalized to IPv4). The hook does not parse forwarding headers. Configure any
proxy that sets the ASGI client address to trust only known ingress peers;
otherwise addresses may collapse to one proxy source or be spoofed upstream.
Missing or invalid addresses are denied. Only keyed source fingerprints and
counts are stored, with one bounded row per action. The next admitted request
in a new minute replaces the previous counters; an idle action retains its
last bucket, so treat the table as restricted operational data. Denied source
requests do not spend the shared allowance.

The database serializes admission per action across workers. Exhaustion returns
429 before authentication or provider work, and database errors fail closed
with 503. Fixed minutes can allow a burst across a boundary. This is a
qualification safeguard, not edge denial-of-service protection; verify limits,
proxy trust, connection budgets and ingress controls in the target environment.

Technical reference: [ASGI client address](https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope).

## Staff access events

Enable INFO for `omnixat.staff_browser.access` and route it to a restricted,
non-blocking handler. This app logger records a fixed action label and HTTP
status after the response starts. Unknown paths collapse to `unmatched`.
It never passes request URLs, queries, headers, client addresses, redirect
locations, cookies, identities, or exception details to the logger. A failed
sink does not change the response. Use a bounded sink and monitor its health
separately; these access events are not a durable audit trail.

In the isolated qualification environment, disable raw access logs on this
virtual host or use a format that omits the request line, query string,
headers, cookies and response Location. Check reverse-proxy, ASGI server,
APM/tracing and provider logs separately; the app cannot redact them. Drive
successful and rejected callbacks using fictional canary values and verify
that each layer's exported logs omit the canaries. Retain only the pass/fail
result, not callback URLs or the test credentials.

Reference: [OAuth Security BCP, credential leakage via browser history](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.3).
