# One-time staff login transactions

This is an internal PostgreSQL component for a future staff OIDC code flow.
It does not expose HTTP, exchange a code, issue a session or contact a provider.

Use `PostgresStaffLoginTransactions` with a fixed HTTPS issuer, staff client ID,
exact registered HTTPS redirect URI and a dedicated 32-byte random server key
from a secret store. Login workers must share the same trusted configuration.
Changing the key or profile invalidates outstanding transactions; start a
fresh login. Do not log the key, state, nonce, browser binding or verifier.

1. The future web adapter generates an independent random browser binding
   with `secrets.token_urlsafe(32)` and keeps it in a host-only, Secure,
   HttpOnly cookie with a SameSite policy compatible with the callback.
   Do not accept the binding from the callback URL or request body.
2. Call `begin` with the binding, then send the returned state, nonce and
   code challenge with method S256 to the configured provider. Use the exact
   same issuer, client ID and redirect URI as the store's configuration.
3. At callback, validate the response issuer (or use a dedicated fixed-issuer
   callback under the provider's qualified mix-up protection). Call `consume`
   with the returned state and original browser cookie before exchanging the
   code. Consume commits before releasing the nonce and PKCE verifier; even if
   the exchange fails or times out, start a fresh login.
4. Exchange the code with the recovered verifier and validate the returned
   ID token using the recovered nonce and the separate
   [staff identity boundary](STAFF_IDENTITY.md). Session creation and the
   web adapter remain to implement.

The database stores only domain-separated HMAC keys for state and browser
binding and a five-minute expiry set by its clock. The nonce and PKCE verifier
are derived from the server key and the bound transaction, never persisted in
raw form. A callback with the wrong binding cannot delete the right transaction.
An atomic DELETE permits only one callback to succeed. Expired transactions
cannot release login material.

Apply migration 0009 as the migration owner. Use a dedicated unprivileged login
with CONNECT, USAGE on `omnixat_staff_login`, SELECT and DELETE on its
transactions table, and column INSERT on `state_key, browser_key` only. Do not
grant role memberships, writes to expiry, or any other application schema.
Use an exclusive idle autocommit connection for each call. The login can delete
stored attempts but cannot derive their credentials from database rows. Before
wiring HTTP, add request rate limits and scheduled pruning of abandoned expired
rows using the expiry index. There is no automatic prune job here.

Protocol references checked 5 November 2026:
[OAuth security best current practice](https://www.rfc-editor.org/rfc/rfc9700.html)
and [PKCE S256](https://www.rfc-editor.org/rfc/rfc7636.html).
