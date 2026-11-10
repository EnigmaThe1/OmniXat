# Actual customer gateway browser qualification

This isolated test harness connects real Chromium, OAuth2 Proxy **7.15.6**, Keycloak
**26.8.2**, the customer ASGI application and disposable PostgreSQL roles/databases.
It starts nothing on import and is not a deployment installer. The existing
customer browser suite keeps its gateway stand-in; this separate suite requires
the actual provider and gateway binaries and fails when prerequisites are absent.

```bash
bash qualification/install_keycloak.sh /tmp/omnixat-keycloak-qualification
bash qualification/install_oauth2_proxy.sh /tmp/omnixat-oauth2-proxy
# Supply OMNIXAT_TEST_ADMIN_DSN for a disposable local PostgreSQL cluster.
OMNIXAT_KEYCLOAK_HOME=/tmp/omnixat-keycloak-qualification \
OMNIXAT_OAUTH2_PROXY_BINARY=/tmp/omnixat-oauth2-proxy \
PYTHONPATH=.:integration_tests \
python3 -m unittest discover -s gateway_browser_tests -v
```

Run from `commercial` with requirements-web-tests.txt and Playwright Chromium
installed. The explicit installer refuses an existing destination and checks the
official Linux amd64 release archive's pinned SHA-256 before extracting the binary.
No binaries or generated credentials are committed. CI runs the new tests alongside
all existing suites, including the unchanged fictional-demo browser approval test.

The gateway configuration comes from `config/oauth2-proxy.customer.example.cfg`.
Only environment bindings, disabled diagnostic logging and an accelerated five-second
refresh interval are supplied by the fixture. The template refresh default is
one minute, below the disposable provider's three-minute access-token lifetime;
operators must align refresh/expiry with their exact provider session policy. Generated private files hold the
32-byte raw cookie key and OIDC client secret. Keycloak's opt-in gateway profile
adds verified email ID-token claims without granting database authority. Access
tokens retain the strict records audience/profile and the API's verifier is unchanged.

All listeners bind loopback. Chromium maps only workspace.example.test to the
high loopback TLS port while retaining the app's canonical HTTPS origin. No root
ports, hosts-file changes, route interception, token injection or mocked protocol
responses are needed. The generated certificate has the fictional DNS name and
loopback IP; Chromium allows only its exact SPKI, with ignore_https_errors=false.
The gateway verifies the provider certificate against that certificate file, and
HTTP fixture probes also verify TLS. The ASGI upstream also uses TLS: the gateway
trusts its exact generated root through Go's SSL_CERT_FILE. Proxy header trust and
insecure upstream certificate bypass remain disabled. Production transport still
needs qualification for the actual certificate and network setup.

Cases cover real form sign-in/PKCE, secure HttpOnly SameSite=Lax __Host- cookies,
attributed organisation/note creation, actual access-token replacement after cookie
refresh, local sign-out, unauthenticated API 401s, missing callback CSRF rejection,
spoofed forwarded headers, viewer write denial and immediate membership revocation.
A server-side observer retains only token digests and verified subject/time metadata.
No raw tokens, passwords, traces, screenshots or provider/gateway private logs are
uploaded. The UI's existing Sign out link clears the local gateway cookie; it does
**not** end the provider SSO session or invalidate copied cookie sessions.

Production MFA/recovery, account switch with pending work, provider-wide logout,
server-side session revocation, key rotation, concurrent refresh and restore/security
qualification remain open. Passing this harness alone does not establish launch
readiness, enable payments or authorise statutory submissions.

Sources checked **10 November 2026**:

- [Official pinned release](https://github.com/oauth2-proxy/oauth2-proxy/releases/tag/v7.15.6)
  and its published Linux amd64 archive SHA-256.
- [Versioned configuration](https://github.com/oauth2-proxy/oauth2-proxy/blob/v7.15.6/docs/docs/configuration/overview.md)
  for raw cookie key files, CA files, access-token forwarding, secure cookies and refresh.
- [Gateway sign-out boundary](https://oauth2-proxy.github.io/oauth2-proxy/features/endpoints/).
- [Chromium's test resolver mapping](https://chromium.googlesource.com/chromium/src/+/673937e2bad1a043d6c00d8a9c4d434507a23179/chrome/test/supervised_user/embedded_test_server_setup_mixin.h).

- [Go certificate roots](https://pkg.go.dev/crypto/x509#SystemCertPool) for the
  explicit fixture SSL_CERT_FILE trust installation.
- [Pinned gateway callback source](https://github.com/oauth2-proxy/oauth2-proxy/blob/v7.15.6/oauthproxy.go)
  for state decoding before missing-CSRF-cookie rejection.

Verified 10 November 2026: [run 42781825221](https://github.com/EnigmaThe1/OmniXat/actions/runs/42781825221)
passed both gateway cases and the complete 503-test pipeline plus container build.
This is bounded compatibility evidence, subject to the open gates above.

## Original-tab recovery and account binding

The recovery profile adds a second generated fictional user and optional evidence
scopes. The recovery class combines the existing constrained evidence fixture with
the real gateway fixture; ordinary gateway/provider cases keep their original
scope. No production realm or grant is installed. The operator template requests
standard OIDC prompt=login for explicit sign-in and recovery. Existing cookie
sessions and refresh continue normally; no active installation is changed.

Three additional cases sign out through the actual gateway in another tab while
leaving original work open. The same-account cases retain provider SSO cookies,
follow the real recovery link, complete a fresh login form in the new tab and check
that the original organisation
input or exact selected-file SHA-256 survives. Successful writes remain attributed
to the initiating user. A repeated same-byte upload retains one quarantined original.
The account-switch case grants a second real user the same editor membership, signs
in through the real password form, requires `409 session_changed` for the original
user's retry, then signs back in as the initiator and confirms one attributed note.

Provider cookies are retained throughout account switching. The real gateway
requests prompt=login, allowing the customer to enter the initiating account
instead of silently reusing the wrong SSO account. No browser-cookie manipulation,
fabricated token, browser request route interception or mocked OIDC response is
used. This does not qualify provider logout or server-side revocation. Recovery
pages have no opener and no persistent browser storage; the context-level new-page
event observes noopener/COOP-separated tabs.

Technical references rechecked 10 November 2026:
[Playwright browser contexts](https://playwright.dev/python/docs/api/class-browsercontext)
for `expect_page`, and the
[pinned gateway endpoints](https://github.com/oauth2-proxy/oauth2-proxy/blob/v7.15.6/docs/docs/features/endpoints.md)
for local cookie clearing versus provider SSO. Actual pass evidence belongs in the
latest development status; implementing a case does not establish that it passes.

The fresh-login request follows [OIDC Core prompt semantics](https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest)
and the maintained gateway's prompt option in its pinned configuration reference.
[Keycloak's current login options](https://www.keycloak.org/securing-apps/javascript-adapter)
also describe enforced login prompts. These sources were rechecked 10 November 2026.
