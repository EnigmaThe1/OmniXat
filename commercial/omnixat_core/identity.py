"""Narrow RFC 9068 access-token verifier using maintained PyJWT.

Pinned server configuration only: no discovery, token-controlled URL fetches, ID-token
acceptance, role mapping, MFA inference or live identity-provider setup.
"""
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey


class AuthenticationError(PermissionError):
    pass


@dataclass(frozen=True, repr=False)
class VerifiedAccess:
    issuer: str
    subject: str
    issued_at: int
    scopes: frozenset[str]


class AccessTokenVerifier:
    def __init__(self, *, issuer, audience, public_keys, max_lifetime=900):
        if not isinstance(issuer, str) or len(issuer) > 2048:
            raise ValueError("Pinned HTTPS issuer required")
        url = urlsplit(issuer)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Pinned HTTPS issuer required")
        if not isinstance(audience, str) or not audience.strip():
            raise ValueError("Pinned audience required")
        if type(max_lifetime) is not int or not 1 <= max_lifetime <= 3600:
            raise ValueError("Bounded token lifetime required")
        keys = dict(public_keys)
        if not keys or any(not isinstance(k, str) or not k or len(k) > 200 or
                           not isinstance(v, RSAPublicKey) or v.key_size < 2048
                           for k, v in keys.items()):
            raise ValueError("Pinned RSA public keys of at least 2048 bits required")
        self.issuer, self.audience = issuer, audience
        self._keys = MappingProxyType(keys)
        self._max_lifetime = max_lifetime

    def verify(self, token):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise ValueError("Invalid token")
            header = jwt.get_unverified_header(token)
            if (header.get('alg') != 'RS256' or header.get('typ') not in ('at+jwt', 'application/at+jwt')
                    or any(k in header for k in ('crit', 'jku', 'jwk', 'x5u', 'b64'))):
                raise ValueError("Unsupported token header")
            key_id = header.get('kid')
            if not isinstance(key_id, str) or key_id not in self._keys:
                raise ValueError("Unknown signing key")
            claims = jwt.decode(token, self._keys[key_id], algorithms=['RS256'],
                                issuer=self.issuer, audience=self.audience,
                                options={'require': ['iss','sub','aud','exp','iat','jti','client_id']})
            for name in ('sub', 'jti', 'client_id'):
                if not isinstance(claims[name], str) or not claims[name].strip() or len(claims[name]) > 255:
                    raise ValueError("Invalid required identity claim")
            for name in ('exp', 'iat') + (('nbf',) if 'nbf' in claims else ()):
                if type(claims[name]) is not int:
                    raise ValueError("Integer token timestamps required")
            if not 0 < claims['exp'] - claims['iat'] <= self._max_lifetime:
                raise ValueError("Token lifetime outside policy")
            scope = claims.get('scope', '')
            if not isinstance(scope, str) or len(scope) > 4096:
                raise ValueError("Invalid scopes")
            return VerifiedAccess(self.issuer, claims['sub'], claims['iat'], frozenset(scope.split()))
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
            # No token, claim values or provider diagnostic is exposed to callers.
            raise AuthenticationError("Access token rejected") from None
