# Revocable staff sessions

Migration 0010 adds an internal PostgreSQL store for opaque staff sessions. A
trusted callback may call `issue_staff_session` only after consuming the
[one-time login attempt](STAFF_LOGIN.md) and exchanging the code with the
configured provider. It passes the ID token from that exchange and the nonce
recovered from the consumed attempt. Issuance verifies the token and checks
current [staff membership](STAFF_IDENTITY.md). Do not expose it as an endpoint
that accepts a caller-supplied ID token, verifier or expected nonce.

The returned token contains 256 random bits. PostgreSQL stores its SHA-256
digest, the membership ID, issuer, subject, original authentication time and
expiry. It stores no raw token, ID token or role snapshot. Expiry is five minutes
from the provider's MFA authentication time. Activity does not extend the
deadline. This is a development policy for staff access.

For each privileged request, `resolve_staff_session` checks the digest and
expiry, then rechecks the current role, matching membership ID, revocation,
authentication cutoff and MFA age. Do not cache the resulting principal.
`revoke_staff_session` durably deletes one session and may be repeated.
Directory revocation or an advanced authentication cutoff blocks all affected
sessions. When granting additional privileges or reactivating a membership,
advance its cutoff in the same update to force fresh authentication. Revocation
applies to subsequent checks; it does not cancel operations already authorised.

Apply migrations as the owner. Grant a dedicated session login CONNECT, USAGE
on `omnixat_staff_session` and SELECT, INSERT and DELETE on its sessions table.
Use a separate, read-only directory login. Neither may inherit other application
grants. Use exclusive idle autocommit connections and short request deadlines.
Protect the trusted session writer as authentication infrastructure; it can
create and delete session records. Never log tokens or pass them to an agent.

No cookie or logout HTTP endpoint, identity provider connection, provider logout
sync, or automatic pruning is included. Before opening owner routes, qualify a
provider's MFA and recovery settings, wire its callback and host-only Secure
HttpOnly cookies, enforce CSRF protection and rate limits, and prune expired rows.
See [NIST session guidance](https://pages.nist.gov/800-63-4/sp800-63b.html#session)
for general session design context.
