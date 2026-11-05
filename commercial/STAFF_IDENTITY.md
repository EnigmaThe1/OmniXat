# Staff identity boundary

This internal adapter verifies the ID token returned by a trusted server-side
OIDC authorisation-code exchange. It uses the existing pinned PyJWT dependency;
it neither selects a provider nor handles a login request. It is separate from
customer bearer verification and cannot issue a tenant principal.

Configure a dedicated staff client, trusted HTTPS issuer, pinned RSA public
keys and the exact authentication context (`acr`) independently verified to
require MFA at that provider. Do not infer MFA from token roles, email, an
`amr` string alone or a provider-neutral name for an assurance class. Qualify
the provider's MFA, recovery and assurance semantics before wiring a route.

`StaffIDTokenVerifier` accepts only the profiled RS256 token, with a single
expected audience, matching authorised party when present, integer timestamps,
an ID token lifetime of at most 600 seconds and an authentication age under
300 seconds. It matches the signed nonce to the trusted login transaction's
nonce (32 random bytes encoded as lowercase hex). It does not consume the
transaction. The future callback must generate and keep that nonce server side,
bind the browser transaction to the chosen issuer and client, verify and
atomically consume state once, and exchange the code using PKCE S256. Never use
a nonce from request parameters as the expected value, or accept an ID token
directly as a bearer credential. Key discovery/rotation is out of scope.

`resolve_staff_login` checks the exact issuer/subject in migration 0008's
staff directory. The current stored role controls access. A revoked row or
authentication at or before its `auth_valid_after` epoch-second cutoff denies
access; issuing a new token for the same authentication does not evade this
cutoff. The returned internal principal is human, interactive, MFA verified,
and has no tenant or bearer scopes. Never persist or cache this principal as
session authority. Existing principals are not retroactively revoked.

Run migrations as the owner. Provision memberships separately using audited
administrative operations; keep revoked records and advance the cutoff when
reactivating or changing the linked identity. Grant a dedicated directory
login CONNECT, USAGE on `omnixat_staff` and SELECT on its memberships table.
Grant no role memberships, other application schemas or writes. The lookup
uses a bounded read-only transaction and forced row security scoped to the
verified issuer/subject. A compromised SQL login can set its own context;
the credential belongs only in the trusted identity backend.

Next: implement one-time login transaction storage and a bounded server-side
session with revocation, then qualify a specific provider's code flow with
fictional accounts. Recheck current membership and MFA on privileged requests
before exposing an owner route.

References checked 5 November 2026: [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html),
[OAuth step-up RFC 9470](https://www.rfc-editor.org/rfc/rfc9470.html),
and the [PyJWT API reference](https://pyjwt.readthedocs.io/en/stable/api.html).
