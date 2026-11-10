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
refresh interval are supplied by the fixture. Generated private files hold the
32-byte raw cookie key and OIDC client secret. Keycloak's opt-in gateway profile
adds verified email ID-token claims without granting database authority. Access
tokens retain the strict records audience/profile and the API's verifier is unchanged.

All listeners bind loopback. Chromium maps only workspace.example.test to the
high loopback TLS port while retaining the app's canonical HTTPS origin. No root
ports, hosts-file changes, route interception, token injection or mocked protocol
responses are needed. The generated certificate has the fictional DNS name and
loopback IP; Chromium allows only its exact SPKI, with ignore_https_errors=false.
The gateway verifies the provider certificate against that certificate file, and
HTTP fixture probes also verify TLS. The ASGI upstream uses private loopback HTTP
only in this disposable harness; production upstream transport needs qualification.

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
