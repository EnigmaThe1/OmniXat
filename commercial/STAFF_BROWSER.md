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
