# Keycloak staff code-flow candidate

`KeycloakStaffLogin` composes the existing PostgreSQL one-time login and staff
session services with an outbound Keycloak authorization-code exchange. This
slice was exercised using HTTPX's fictional provider transport and a disposable
PostgreSQL cluster. It does not qualify a real realm or install HTTP routes.

The adapter accepts only trusted configuration: a fixed HTTPS realm issuer
ending in `/realms/<realm>`, exact HTTPS callback URI, dedicated confidential
staff client, URL-safe client secret, login derivation key, pinned RSA public
keys, and a provider-specific MFA ACR. Keep secrets out of source and logs.
The default Keycloak realm layout is required; other endpoint layouts are not
supported here. The token endpoint is derived from that exact realm, with no
discovery or callback-controlled destination.

- `begin` persists browser-bound state and returns a provider URL with a nonce,
  PKCE S256, the requested MFA ACR and a fresh authentication request.
- `complete` requires an exact response issuer before consuming state. It
  consumes the attempt once, exchanges the code with the stored verifier and
  confidential-client credentials, then verifies the returned ID token against
  the stored nonce before issuing a staff session. Start a fresh attempt after
  an exchange failure. Access and refresh tokens are neither returned nor saved.
- The exchange uses TLS verification, does not follow redirects or use
  environment proxies, limits response bytes and bounds waiting for the body.
  Upstream errors are not passed to callers. The future HTTP route must also
  enforce its own end-to-end request deadline.

Before wiring a browser callback, qualify an isolated realm using fictional
accounts. Enable confidential client authentication, Standard Flow, PKCE S256
and the authorization response `iss` parameter. Register only the exact
callback, disable unused grants, and configure the actual MFA flow and ACR
mapping. Verify that the selected realm returns the expected `iss`, nonce,
`auth_time`, audience and MFA assurance for a successful sign-in, and does
not return the approved assurance after password-only login or recovery.
Confirm signing key handling and rotation, issuer/realm mismatch, replay
and revoked staff cases. This repository contains no realm credentials.

The future web adapter must reject repeated callback parameters, take the
binding from a host-only Secure HttpOnly cookie, protect state-changing
requests against CSRF, rate-limit starts and callbacks, scrub sensitive URL
parameters from request logs, and prune expired attempts and sessions.
Keep owner routes gated until those checks and the realm qualification pass.

References reviewed 5 November 2026: [Keycloak OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers),
[Keycloak server administration](https://www.keycloak.org/docs/latest/server_admin/index.html),
[OAuth response issuer RFC 9207](https://www.rfc-editor.org/rfc/rfc9207.html)
and [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/).
