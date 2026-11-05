from time import time
import unittest

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from omnixat_core.identity import AccessTokenVerifier, AuthenticationError
from omnixat_core.staff_identity import StaffIDTokenVerifier


class StaffIDTokenTests(unittest.TestCase):
    issuer = "https://staff.example.invalid"
    client = "fictional-staff-client"
    acr = "urn:example:fictional:mfa"
    nonce = "ab" * 32

    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.verifier = StaffIDTokenVerifier(issuer=cls.issuer, client_id=cls.client,
                                          public_keys={"test": cls.key.public_key()}, mfa_acr=cls.acr)

    def claims(self):
        now = int(time())
        return dict(iss=self.issuer, sub="fictional-subject", aud=self.client, iat=now,
                    exp=now + 60, auth_time=now - 5, nonce=self.nonce, acr=self.acr)

    def token(self, claims, *, key=None, **headers):
        return jwt.encode(claims, key or self.key, algorithm="RS256", headers={"kid": "test", **headers})

    def test_success_for_single_audience_ignores_role_and_email_claims(self):
        claims = self.claims()
        for audience in (self.client, [self.client]):
            claims.update(aud=audience, azp=self.client, role="platform_owner", email="fictional@example.invalid")
            login = self.verifier.verify(self.token(claims), expected_nonce=self.nonce)
            self.assertEqual((login.issuer, login.subject, login.authenticated_at),
                             (self.issuer, claims["sub"], claims["auth_time"]))
            self.assertNotIn(claims["sub"], repr(login))

    def test_denies_wrong_login_transaction(self):
        for nonce in (None, "cd" * 32, self.nonce.upper(), "short"):
            with self.subTest(nonce=nonce), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(self.claims()), expected_nonce=nonce)

    def test_denies_wrong_issuer_audience_or_authorised_party(self):
        for change in ({"iss": "https://tenant.example.invalid"}, {"aud": "tenant-api"},
                       {"aud": [self.client, "tenant-api"]}, {"azp": "other-client"}, {"azp": None}):
            with self.subTest(change=change), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(self.claims() | change), expected_nonce=self.nonce)

    def test_denies_unqualified_mfa_or_old_authentication_even_on_new_token(self):
        base = self.claims()
        for change in ({"acr": "0", "amr": ["mfa"], "mfa_verified": True},
                       {"auth_time": base["iat"] - 300}, {"auth_time": base["iat"] + 1},
                       {"auth_time": str(base["auth_time"])}, {"auth_time": True},
                       {"iat": base["iat"] + 60}, {"exp": base["iat"] - 1},
                       {"exp": base["iat"] + 601}, {"nonce": "cd" * 32}):
            with self.subTest(change=change), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(base | change), expected_nonce=self.nonce)
        for claim in ("acr", "auth_time", "nonce"):
            missing = base.copy()
            del missing[claim]
            with self.subTest(claim=claim), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(missing), expected_nonce=self.nonce)

    def test_signing_key_and_untrusted_header_rejected(self):
        for change in ({"key": self.other_key}, {"kid": "unknown"},
                       {"jku": "https://key.example.invalid"}, {"crit": ["private"]},
                       {"typ": "at+jwt"}):
            with self.subTest(change=change), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(self.claims(), **change), expected_nonce=self.nonce)
        unsigned = jwt.encode(self.claims(), key="", algorithm="none", headers={"kid": "test"})
        with self.assertRaises(AuthenticationError):
            self.verifier.verify(unsigned, expected_nonce=self.nonce)

    def test_staff_id_token_is_not_accepted_by_tenant_bearer_verifier(self):
        access = AccessTokenVerifier(issuer=self.issuer, audience=self.client,
                                     public_keys={"test": self.key.public_key()})
        token = self.token(self.claims() | {"jti": "test", "client_id": self.client, "scope": "records:read"})
        with self.assertRaises(AuthenticationError):
            access.verify(token)
