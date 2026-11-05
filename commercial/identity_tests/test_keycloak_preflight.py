from base64 import urlsafe_b64encode
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from omnixat_core.keycloak_preflight import check_realm, keycloak_endpoints, main


def _encoded_integer(number):
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class RealmPreflightTests(unittest.TestCase):
    issuer = "https://id.example.invalid/realms/fictional"

    @classmethod
    def setUpClass(cls):
        def key(kid):
            pub = generate_private_key(public_exponent=65537, key_size=2048).public_key()
            numbers = pub.public_numbers()
            jwk = dict(kid=kid, kty="RSA", use="sig", alg="RS256",
                       e=_encoded_integer(numbers.e), n=_encoded_integer(numbers.n))
            pin = sha256(pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).hexdigest()
            return jwk, pin

        cls.active, cls.active_pin = key("fictional-active")
        cls.rotating, cls.rotating_pin = key("fictional-rotating")

    def setUp(self):
        protocol = self.issuer + "/protocol/openid-connect/"
        self.metadata = dict(
            issuer=self.issuer, authorization_endpoint=protocol + "auth",
            token_endpoint=protocol + "token", jwks_uri=protocol + "certs",
            response_types_supported=["code"], response_modes_supported=["query"],
            grant_types_supported=["authorization_code"], scopes_supported=["openid"],
            token_endpoint_auth_methods_supported=["client_secret_basic"],
            code_challenge_methods_supported=["S256"], id_token_signing_alg_values_supported=["RS256"],
            authorization_response_iss_parameter_supported=True,
        )
        self.pins = {self.active["kid"]: self.active_pin}
        self.jwks = {"keys": [self.active, self.rotating]}

    def test_accepts_matching_profile_and_explicit_rotation_pins(self):
        check_realm(self.issuer, self.metadata, self.jwks, self.pins)
        check_realm(self.issuer, self.metadata, self.jwks, self.pins | {self.rotating["kid"]: self.rotating_pin})

    def test_refuses_metadata_endpoint_or_issuer_substitution(self):
        for field in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                check_realm(self.issuer, self.metadata | {field: "https://other.example.invalid"},
                            self.jwks, self.pins)

    def test_requires_pkce_issuer_binding_and_client_profile(self):
        for change in (
            {"code_challenge_methods_supported": ["plain"]},
            {"authorization_response_iss_parameter_supported": 1},
            {"response_modes_supported": ["form_post"]},
            {"token_endpoint_auth_methods_supported": ["client_secret_post"]},
            {"id_token_signing_alg_values_supported": "RS256"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_realm(self.issuer, self.metadata | change, self.jwks, self.pins)

    def test_refuses_replaced_duplicate_private_or_wrong_use_key(self):
        for keys in (
            [self.rotating | {"kid": self.active["kid"]}],
            [self.active, self.active],
            [self.active | {"d": "private"}],
            [self.active | {"use": "enc"}],
            [self.active | {"e": "AQAB="}],
            [self.active | {"key_ops": ["sign"]}],
            [self.rotating],
        ):
            with self.subTest(keys=len(keys)), self.assertRaises(ValueError):
                check_realm(self.issuer, self.metadata, {"keys": keys}, self.pins)

    def test_profile_refuses_unsafe_or_unsupported_realm_urls(self):
        for issuer in ("http://id.example.invalid/realms/fictional",
                       "https://name@id.example.invalid/realms/fictional",
                       "https://id.example.invalid/auth/realms/fictional",
                       "https://id.example.invalid/realms/..",
                       "https://id.example.invalid/realms/fictional#fragment"):
            with self.subTest(issuer=issuer), self.assertRaises(ValueError):
                keycloak_endpoints(issuer)

    def test_cli_reports_only_pass_or_generic_failure_and_limits_input(self):
        with TemporaryDirectory() as temp:
            metadata, jwks = (Path(temp) / name for name in ("metadata.json", "jwks.json"))
            metadata.write_text(json.dumps(self.metadata), encoding="utf-8")
            jwks.write_text(json.dumps(self.jwks), encoding="utf-8")
            argv = ["--issuer", self.issuer, "--metadata", str(metadata), "--jwks", str(jwks),
                    "--pin", self.active["kid"] + "=" + self.active_pin]

            def run():
                output = StringIO()
                with redirect_stdout(output):
                    status = main(argv)
                self.assertNotIn(self.issuer, output.getvalue())
                self.assertNotIn(self.active_pin, output.getvalue())
                return status, output.getvalue()

            self.assertEqual(run()[0], 0)
            for body in (b'{"issuer":"redacted","issuer":"duplicate"}', b" " * (256 * 1024 + 1)):
                metadata.write_bytes(body)
                status, output = run()
                self.assertEqual(status, 1)
                self.assertTrue(output.startswith("FAIL:"))
                self.assertNotIn("redacted", output)
