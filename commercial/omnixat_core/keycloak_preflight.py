"""Offline operator check for the pinned Keycloak staff adapter profile."""
import argparse
from base64 import b64decode, urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_MAX_DOCUMENT_BYTES = 256 * 1024


def keycloak_endpoints(issuer):
    if (not isinstance(issuer, str) or not 1 <= len(issuer) <= 2048
            or any(not 33 <= ord(char) <= 126 or char in "\\?#" for char in issuer)):
        raise ValueError("Expected a pinned HTTPS Keycloak realm issuer")
    parsed = urlsplit(issuer)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or not re.fullmatch(r"/realms/[A-Za-z0-9._~-]{1,128}", parsed.path)
            or parsed.path.rsplit("/", 1)[-1] in (".", "..")):
        raise ValueError("Expected a pinned HTTPS Keycloak realm issuer")
    base = issuer + "/protocol/openid-connect/"
    return {"authorization_endpoint": base + "auth", "token_endpoint": base + "token",
            "jwks_uri": base + "certs"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _read(path):
    with Path(path).open("rb") as file:
        raw = file.read(_MAX_DOCUMENT_BYTES + 1)
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise ValueError("Metadata or JWKS document exceeds size limit")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def _uint(value, *, max_bytes):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,%d}" % ((max_bytes * 4 + 2) // 3), value):
        raise ValueError("Invalid RSA key encoding")
    raw = b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if (not raw or len(raw) > max_bytes or raw[0] == 0
            or urlsafe_b64encode(raw).decode("ascii").rstrip("=") != value):
        raise ValueError("Invalid RSA key encoding")
    return int.from_bytes(raw, "big")


def check_realm(issuer, metadata, jwks, pins):
    """Check public metadata against an independently approved kid-to-SPKI map."""
    expected = {"issuer": issuer, **keycloak_endpoints(issuer)}
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise ValueError("Realm metadata mismatch: " + field)
    for field, feature in (
        ("response_types_supported", "code"),
        ("response_modes_supported", "query"),
        ("grant_types_supported", "authorization_code"),
        ("scopes_supported", "openid"),
        ("token_endpoint_auth_methods_supported", "client_secret_basic"),
        ("code_challenge_methods_supported", "S256"),
        ("id_token_signing_alg_values_supported", "RS256"),
    ):
        values = metadata.get(field)
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values) or feature not in values:
            raise ValueError("Realm metadata missing required capability: " + field)
    if metadata.get("authorization_response_iss_parameter_supported") is not True:
        raise ValueError("Realm must advertise the authorization response issuer")
    if not pins or any(not isinstance(kid, str) or not 1 <= len(kid) <= 200
                       or not isinstance(pin, str) or not re.fullmatch(r"[a-f0-9]{64}", pin)
                       for kid, pin in pins.items()):
        raise ValueError("Independent SHA-256 SPKI pins required")
    entries = jwks.get("keys")
    if not isinstance(entries, list) or not entries or len(entries) > 64:
        raise ValueError("Invalid realm key set")
    keys = {}
    for entry in entries:
        if not isinstance(entry, dict) or any(k in entry for k in ("d", "p", "q", "dp", "dq", "qi", "oth", "k")):
            raise ValueError("Expected a public realm key set")
        kid = entry.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 200 or kid in keys:
            raise ValueError("Missing or duplicate realm key ID")
        keys[kid] = entry
    for kid, pin in pins.items():
        key = keys.get(kid, {})
        if (key.get("kty") != "RSA" or key.get("use", "sig") != "sig"
                or key.get("alg", "RS256") != "RS256" or key.get("key_ops", ["verify"]) != ["verify"]):
            raise ValueError("Approved RSA signing key missing or incompatible")
        public_key = RSAPublicNumbers(_uint(key.get("e"), max_bytes=8),
                                      _uint(key.get("n"), max_bytes=1024)).public_key()
        if public_key.key_size < 2048:
            raise ValueError("Approved RSA signing key is too small")
        der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        if not compare_digest(sha256(der).hexdigest(), pin):
            raise ValueError("Approved RSA signing key fingerprint mismatch")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--metadata", required=True, help="Saved realm discovery JSON")
    parser.add_argument("--jwks", required=True, help="Saved realm public JWKS JSON")
    parser.add_argument("--pin", required=True, action="append", metavar="KID=SHA256",
                        help="Independently approved DER SPKI fingerprint; repeat during rotation")
    args = parser.parse_args(argv)
    try:
        pins = {}
        for item in args.pin:
            kid, separator, pin = item.rpartition("=")
            if not separator or not kid or kid in pins:
                raise ValueError("Invalid or duplicate pin")
            pins[kid] = pin
        check_realm(args.issuer, _read(args.metadata), _read(args.jwks), pins)
    except (OSError, ValueError, RecursionError):
        print("FAIL: realm metadata or public keys do not match the pinned staff profile")
        return 1
    print("PASS: metadata and public-key pins match; browser MFA qualification still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
