"""Pinned Keycloak staff code flow, without browser routes or provider provisioning."""
import json
import re
from time import monotonic
from urllib.parse import urlencode

import httpx

from .identity import AuthenticationError
from .keycloak_preflight import keycloak_endpoints, _unique_object
from .staff_identity import StaffIDTokenVerifier
from .staff_login_postgres import PostgresStaffLoginTransactions
from .staff_sessions_postgres import issue_staff_session

_MAX_RESPONSE_BYTES = 65536
_MAX_EXCHANGE_SECONDS = 5


class KeycloakStaffLogin:
    """Configure from trusted settings only; transport injection is for trusted tests."""

    def __init__(self, *, issuer, client_id, redirect_uri, client_secret, login_key,
                 public_keys, mfa_acr, transport=None):
        self._attempts = PostgresStaffLoginTransactions(
            issuer=issuer, client_id=client_id, redirect_uri=redirect_uri, key=login_key)
        self._endpoints = keycloak_endpoints(issuer)
        if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{1,255}", client_id):
            raise ValueError("Expected a URL-safe staff client ID")
        if not isinstance(client_secret, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{16,512}", client_secret):
            raise ValueError("Expected a URL-safe confidential-client secret")
        self._verifier = StaffIDTokenVerifier(
            issuer=issuer, client_id=client_id, public_keys=public_keys, mfa_acr=mfa_acr)
        self._issuer = issuer
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._client_secret = client_secret
        self._mfa_acr = mfa_acr
        self._transport = transport

    def begin(self, attempts, *, browser_binding) -> str:
        """Create an attempt and return the provider URL for a trusted web adapter."""
        attempt = self._attempts.begin(attempts, browser_binding=browser_binding)
        query = urlencode({
            "response_type": "code", "response_mode": "query", "scope": "openid",
            "client_id": self._client_id, "redirect_uri": self._redirect_uri,
            "state": attempt.state, "nonce": attempt.nonce,
            "code_challenge": attempt.code_challenge, "code_challenge_method": "S256",
            "acr_values": self._mfa_acr, "max_age": "0",
        })
        return self._endpoints["authorization_endpoint"] + "?" + query

    def complete(self, attempts, sessions, directory, *, state, browser_binding, response_issuer, code) -> str:
        """Consume before exchange. After any exchange failure, restart the login."""
        if response_issuer != self._issuer or not isinstance(code, str) or not 1 <= len(code) <= 4096:
            raise AuthenticationError("Staff login callback rejected")
        if not code.isascii() or any(not 33 <= ord(char) <= 126 for char in code):
            raise AuthenticationError("Staff login callback rejected")
        attempt = self._attempts.consume(attempts, state=state, browser_binding=browser_binding)
        token = self._exchange(code, attempt.code_verifier)
        return issue_staff_session(sessions, directory, self._verifier, token, expected_nonce=attempt.nonce)

    def _exchange(self, code, code_verifier):
        deadline = monotonic() + _MAX_EXCHANGE_SECONDS
        try:
            with httpx.Client(transport=self._transport, trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(2.0)) as client:
                with client.stream(
                    "POST", self._endpoints["token_endpoint"],
                    auth=httpx.BasicAuth(self._client_id, self._client_secret),
                    data={"grant_type": "authorization_code", "code": code,
                          "redirect_uri": self._redirect_uri, "code_verifier": code_verifier},
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as response:
                    if (response.status_code != 200
                            or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                            or response.headers.get("content-encoding", "identity").lower() != "identity"):
                        raise ValueError
                    body = bytearray()
                    for chunk in response.iter_raw():
                        if monotonic() >= deadline or len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise ValueError
                        body.extend(chunk)
                    if monotonic() >= deadline:
                        raise ValueError
            data = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or "error" in data:
                raise ValueError
            token = data.get("id_token")
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise ValueError
            return token
        except (httpx.HTTPError, ValueError, RecursionError):
            raise AuthenticationError("Staff provider exchange rejected") from None
