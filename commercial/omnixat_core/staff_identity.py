"""Validate a staff OIDC ID token after a trusted server-side code exchange."""
from dataclasses import dataclass
from hmac import compare_digest
import re
from time import time

import jwt

from .identity import AuthenticationError, _pinned_rsa_keys


@dataclass(frozen=True, repr=False)
class VerifiedStaffLogin:
    issuer: str
    subject: str
    authenticated_at: int


class StaffIDTokenVerifier:
    """Narrow RS256 profile. A caller must consume the login transaction once."""

    def __init__(self, *, issuer, client_id, public_keys, mfa_acr):
        self._keys = _pinned_rsa_keys(issuer, client_id, public_keys)
        if not isinstance(mfa_acr, str) or not 1 <= len(mfa_acr) <= 255 or mfa_acr == '0' or not mfa_acr.strip():
            raise ValueError("Pin a provider-qualified MFA assurance class")
        self._issuer = issuer
        self._client_id = client_id
        self._mfa_acr = mfa_acr

    def verify(self, token, *, expected_nonce):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise ValueError
            if not isinstance(expected_nonce, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_nonce):
                raise ValueError
            header = jwt.get_unverified_header(token)
            if (header.get('alg') != 'RS256' or header.get('typ') not in (None, 'JWT')
                    or any(k in header for k in ('crit', 'jku', 'jwk', 'x5u', 'b64'))):
                raise ValueError
            key_id = header.get('kid')
            if not isinstance(key_id, str) or key_id not in self._keys:
                raise ValueError
            claims = jwt.decode(token, self._keys[key_id], algorithms=['RS256'],
                                issuer=self._issuer, audience=self._client_id,
                                options={'require': ['iss', 'sub', 'aud', 'iat', 'exp',
                                                     'nonce', 'acr', 'auth_time']})
            if claims['aud'] not in (self._client_id, [self._client_id]):
                raise ValueError
            if 'azp' in claims and claims['azp'] != self._client_id:
                raise ValueError
            nonce = claims['nonce']
            if not isinstance(nonce, str) or not nonce.isascii() or not compare_digest(nonce, expected_nonce):
                raise ValueError
            subject = claims['sub']
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 255 or '\x00' in subject:
                raise ValueError
            if claims['acr'] != self._mfa_acr:
                raise ValueError
            if any(type(claims[k]) is not int for k in ('iat', 'exp', 'auth_time', 'nbf') if k in claims):
                raise ValueError
            issued, expires, authenticated = (claims[k] for k in ('iat', 'exp', 'auth_time'))
            if not 0 < expires - issued <= 600 or not 0 < authenticated <= issued or time() - authenticated >= 300:
                raise ValueError
            return VerifiedStaffLogin(self._issuer, subject, authenticated)
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError, OverflowError):
            raise AuthenticationError("Staff authentication denied") from None
