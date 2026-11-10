# Customer identity: real Keycloak qualification

This opt-in harness exercises **Keycloak 26.8.2**, not synthetic provider responses.
It is a disposable test fixture, not a realm deployment or a production installer.
The existing production access-token verifier and database identity/membership
services are unchanged. Nothing is activated by importing the app.

## Run

Install the existing `requirements-web-tests.txt` and Java 21. Supply an explicit
disposable PostgreSQL cluster admin DSN, as for the existing integration tests.
The suite creates/drops its own random database and constrained runtime roles.
From `commercial/`:

```bash
bash qualification/install_keycloak.sh /tmp/omnixat-keycloak-qualification
export OMNIXAT_KEYCLOAK_HOME=/tmp/omnixat-keycloak-qualification
# Supply OMNIXAT_TEST_ADMIN_DSN privately; never commit or print it.
PYTHONPATH=.:integration_tests python3 -m unittest discover -s provider_tests -v
```

The installer downloads the exact official archive and checks its independently
recorded release SHA-256 before extraction:
`dd124787283918bc597628887168333465ee2a811a389e0003569e52be7e487f`.
It refuses an existing destination. It does not start a server. CI uses this same
script and the runner's Java 21; missing prerequisites fail, never skip a test.

The fixture copies the installation into a private temporary directory, generates
a random fictional account and client secret, and creates a short-lived loopback
TLS certificate/private key. It listens only on `127.0.0.1`, uses an isolated local
H2 database and has no administrator credentials. Startup is bounded; the process
is terminated and private temporary files removed on success or failure. No ambient
DSN, credential, proxy or JVM hook is passed in the provider process environment.
Provider startup/authentication logs and token responses are not published as CI
artifacts. Never run this development-mode realm with real accounts or records.

HTTP clients verify the generated certificate, exact issuer and fixed same-realm
endpoints, do not use environment proxies or automatically follow redirects, and
stop at the exact fictional callback URI. They submit the actual Keycloak login
form and exchange actual authorization codes with S256 PKCE. ID-token nonce, issuer,
audience, signature and fixture subject are checked before using the access token.
No browser login or OAuth2 Proxy session is simulated by this particular harness;
the existing separate browser suite still uses its documented gateway stand-in.

## Qualified profile and checks

The minimal client has only code flow, exact callback and mandatory S256. It has
no password grant, service-account grant, implicit flow, registration or password
recovery. The `records:read` client scope is default; `records:write` is optional
and requested explicitly. No email, role, staff or filing-approval mapper is used.

Three explicit mappers provide the access-token subject (`oidc-sub-mapper`),
`omnixat-records` audience and dedicated `client_id`. The client enables
`access.token.header.type.rfc9068` and RS256, with a 180-second access lifetime.
The actual minimal realm initially omitted access-token `sub`; the unchanged
strict verifier rejected it. Adding the explicit subject mapper fixes the provider
profile rather than relaxing the verifier. Required token claims are not assumed
from an ID token, `azp`, a username header or a default client scope.

The test fixture explicitly installs only the fresh realm's TLS-verified RS256
signing keys into its test verifier. This is operator-controlled ephemeral fixture
trust, **not** automatic key discovery/approval in production. Production still
requires independently approved public keys and controlled rotation.

| Check | Evidence exercised |
|---|---|
| Actual code login | Keycloak form, state/response issuer, nonce, S256 and strict signed access-token verification |
| Token purpose | Actual provider ID token and wrong API audience rejected |
| Persistent authority | Current directory/context, attributed note creation and same-key replay through real PostgreSQL/HTTP services |
| Tenant/role/revocation | Different tenant, viewer writes, identity cutoff and unprovisioned subject denied despite a signed token |
| Client scope | Actual read-only provider token cannot write as a persisted editor |
| PKCE and code replay | Missing S256 returns callback `invalid_request` without a code; wrong verifier and code reuse rejected |
| Refresh | Actual refresh preserves the access profile; rotated refresh-token reuse rejected |
| Disabled grants | Password and client-credentials requests return `unauthorized_client` |

## Remaining production acceptance

This is a narrow maintained-provider protocol/service compatibility result. It does
not qualify a complete customer identity service or the whole platform. The fixture
performs HTTP form/code exchange, not a real-browser provider login. OAuth2 Proxy
redirect/cookie issuance and renewal, account switching, full logout/provider-session
revocation, MFA/passkeys, recovery/email flows, signing-key rotation and operator
onboarding remain to qualify with fictional accounts. The profile deliberately
omits the email/profile mappings a browser gateway will need; it must not be copied
unreviewed into a live realm. A provider-signed token still grants no membership,
owner/staff authority or statutory approval by itself.

Sources checked **10 November 2026**:

- [Official Keycloak 26.8.2 release](https://github.com/keycloak/keycloak/releases/tag/26.8.2) and release-asset SHA-256 metadata.
- [Keycloak RFC 9068 header setting](https://github.com/keycloak/keycloak/blob/26.8.2/server-spi-private/src/main/java/org/keycloak/protocol/oidc/OIDCConfigAttributes.java).
- [Keycloak hardcoded claim mapper](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/protocol/oidc/mappers/HardcodedClaim.java).
- [OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers) and [access token profile RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html).
- [Ubuntu 24.04 runner Java inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md).

No production dependency, legal rule, provider contract, public listener, payment or
statutory transport was changed by this qualification increment.

## Actual Chromium provider login

`PYTHONPATH=.:integration_tests python3 -m unittest discover -s provider_browser_tests -v`
with the same Keycloak installation and installed Playwright Chromium exercises the
actual provider login page over loopback TLS. The fixture certificate's generated
SPKI SHA-256 is the only browser certificate exception; ignore_https_errors remains
false. The existing HTTP client still verifies that certificate normally.

The browser submits a real password form. The fixed fictional callback navigation is captured, and its hostname is forced
unresolvable by Chromium to prevent external traffic. The test driver validates state/response issuer,
exchanges the actual code, checks ID-token nonce/signature and verifies the actual
access token with the unchanged verifier. Tokens are never injected into the page.
A second case checks that a wrong password shows an error without releasing a code.
No screenshots, browser traces, tokens or credentials from these tests are uploaded.
This extends provider-browser compatibility; it does not exercise OAuth2 Proxy or
claim gateway-cookie issuance, session renewal/logout, MFA/recovery or production
readiness. CI retains all existing provider/service/customer/prototype checks.

Technical references checked 10 November 2026: Playwright Page expect_request
https://playwright.dev/python/docs/api/class-page and Chromium SPKI certificate pin
https://chromium.googlesource.com/chromium/src/+/3391e936295e694b35688b2152103b8d1432153d/chrome/common/chrome_switches.cc .
