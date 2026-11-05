# Identity and membership boundary — C1 second slice

This is a resource-service adapter, not a login server or a completed identity-provider
integration. It verifies signed bearer access tokens with maintained PyJWT and resolves
persistent workspace membership before calling the existing record repository. No
provider account, browser login, live service or statutory submission is activated.

## Trust model and configuration

Install `requirements-identity.txt` for the optional adapter/tests. The exercised
versions are PyJWT 2.13.0, cryptography 50.0.0 and psycopg 3.3.8 on Python 3.12.
The dependency-free core remains separate.

Create one server-owned `AccessTokenVerifier` with a pinned HTTPS issuer, intended
API audience, and mapping of key IDs to trusted RSA public-key objects (2048 bits or
larger). Never accept verifier configuration, key material or issuer selection from
request input. Configure/refresh public keys out of band through an authenticated,
reviewed provider-metadata process; no automatic JWKS/discovery client exists here.
Replacing a verifier atomically can remove old keys; unknown IDs fail closed.

The implemented access-token profile uses RS256 and `at+jwt` (or
`application/at+jwt`) type, distinguishing access tokens from ID tokens. Signature,
issuer, audience, required claims and validity timestamps are checked. Tokens must
include subject, issue/expiry times, token ID and client ID. Integer timestamps and
bounded strings are enforced; default maximum lifetime is 900 seconds, configurable
up to 3600 seconds with no clock leeway. Optional `nbf` is checked. Unsupported
critical/key-source headers, unsigned/symmetric tokens and untrusted key IDs fail.
No token-controlled network fetch occurs. This intentionally supports a narrow
RFC 9068 profile; do not assume arbitrary provider defaults conform.

No tokens, private signing keys, provider diagnostics or full claim sets are stored
or logged by these modules. Test keys are generated in memory. The verified object
retains only issuer, subject, issue time and scopes and does not display them in repr.

## Persistent access and revocation

Migration `0002_identity_memberships.sql` adds:

- Identity links keyed by issuer/subject, internal user ID, human/agent actor type,
  disabled timestamp and token cutoff.
- Tenant/user memberships with owner/editor/viewer role and revoked timestamp.
- Forced RLS for the identity/tenant-bound lookup, SELECT-only runtime permissions.

Provision identity links and memberships only through a separate trusted administrative
service/operation. The runtime needs SELECT on these two tables, in addition to
existing repository grants. It cannot self-enrol, change roles/actor kinds or clear
revocation. No account/membership administration endpoint is implemented. Email,
token roles, requested tenant claims and model instructions cannot create membership.

Use `authenticated_records(connection, server_verifier, access_token, tenant_uuid,
write=False)` at the service boundary. A valid token alone gives no workspace access.
The adapter verifies it, then checks the exact identity and active membership in the
same database transaction as the record operations. Every new unit of work re-reads
membership; no principal/membership cache exists. Disabling an identity or revoking a
membership denies the next unit. Set `tokens_valid_after` to an integer epoch second
to reject tokens issued at or before that cutoff. Role downgrades are also observed
without reissuing the token. Separate memberships may have independent roles.

Revocation does not cancel a unit already in progress; token expiry is checked on
entry. Enforce short request/transaction deadlines in the upcoming transport and
recheck authority at sensitive dispatch points. Per-token/session revocation,
provider logout events and online introspection are not yet implemented.

Record scopes are the intersection of signed token scopes and a fixed records-only
allowlist; database roles supply the other permission boundary. The created Principal
has no staff role, no verified MFA and explicit API scopes. Human and agent bearer
principals cannot approve filings, manage subscriptions or administer memberships.
A secure interactive review session remains a separate future service.

## Limits and next work

The original `tenant_records` API remains an internal trusted-principal entry point
for existing callers/tests; never expose it as a route accepting Principal/role headers.
RLS remains defence against missing query filters, not a compromised SQL runtime.
Complete entity grants, audited provisioning, provider onboarding, automatic key
rotation, OIDC authorisation-code/PKCE login, CSRF/session/logout/recovery controls,
MFA step-up and production qualification remain unfinished. No provider was selected
or advertised as integrated based solely on synthetic token tests.

The first [authenticated record transport](HTTP_API.md) now uses this adapter.
Next: durable creation idempotency/audit and a separately qualified maintained-provider browser login flow.
Preserve the bearer/human-approval separation.

## Verification

```bash
cd commercial
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s identity_tests -v
python3 -m unittest discover -s integration_tests -v
```

Integration requires the explicitly configured disposable PostgreSQL test cluster
from [POSTGRES.md](POSTGRES.md). Current results: 32 core, 9 token tests and 37
PostgreSQL integration tests pass, including legacy-schema upgrade preservation.
The existing fictional demo browser prerequisite failure is separate and unchanged.

Primary technical sources checked 5 November 2026:

- [RFC 9068 access-token profile and validation](https://www.rfc-editor.org/rfc/rfc9068.html)
- [PyJWT decode configuration and required claims](https://pyjwt.readthedocs.io/en/stable/api.html)

No legal rule, amount or filing capability changed in this increment.
