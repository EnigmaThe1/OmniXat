"""Fictional tokens; signing keys are generated in memory and never persisted."""
import time
import unittest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from omnixat_core.identity import AccessTokenVerifier, AuthenticationError


class AccessTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.verifier = AccessTokenVerifier(issuer='https://identity.example.test', audience='omnixat-records',
                                         public_keys={'test-key': cls.key.public_key()})

    def claims(self, **changes):
        now = int(time.time())
        return dict(iss='https://identity.example.test', aud='omnixat-records', sub='fictional-user',
                    iat=now-1, exp=now+300, jti='fictional-token', client_id='fictional-app',
                    scope='records:read records:write') | changes

    def token(self, claims=None, **headers):
        return jwt.encode(claims if claims is not None else self.claims(), self.key, algorithm='RS256',
                          headers={'kid':'test-key','typ':'at+jwt'} | headers)

    def test_valid_signature_returns_only_minimal_verified_identity(self):
        verified = self.verifier.verify(self.token(self.claims(role='owner', mfa=True, tenant_id='untrusted')))
        self.assertEqual(verified.subject, 'fictional-user')
        self.assertEqual(verified.scopes, frozenset({'records:read','records:write'}))
        self.assertFalse(hasattr(verified, 'role'))
        self.assertNotIn('fictional-user', repr(verified))

    def test_rejects_wrong_issuer_audience_expired_and_future_tokens(self):
        now = int(time.time())
        for changes in [{'iss':'https://attacker.example.test'}, {'aud':'other-api'},
                        {'iat':now-400,'exp':now-1}, {'iat':now+300,'exp':now+600},
                        {'nbf':now+300}]:
            with self.subTest(changes=changes), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(self.claims(**changes)))

    def test_all_mandatory_claims_are_required(self):
        for name in ('iss','sub','aud','exp','iat','jti','client_id'):
            claims = self.claims()
            del claims[name]
            with self.subTest(name=name), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(claims))

    def test_rejects_bad_signature_unsigned_and_symmetric_tokens(self):
        candidates = [jwt.encode(self.claims(), self.other_key, algorithm='RS256',
                                 headers={'kid':'test-key','typ':'at+jwt'}),
                      jwt.encode(self.claims(), '', algorithm='none', headers={'kid':'test-key','typ':'at+jwt'}),
                      jwt.encode(self.claims(), 'fictional-test-material-with-enough-length', algorithm='HS256',
                                 headers={'kid':'test-key','typ':'at+jwt'})]
        for token in candidates:
            with self.assertRaises(AuthenticationError):
                self.verifier.verify(token)

    def test_id_tokens_unknown_keys_and_token_key_urls_are_rejected(self):
        for headers in [{'typ':'JWT'}, {'kid':'unknown'}, {'jku':'https://attacker.example.test/keys'},
                        {'jwk':{'kty':'RSA'}}, {'x5u':'https://attacker.example.test/key'}, {'crit':['unsupported']}]:
            with self.subTest(headers=headers), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(**headers))

    def test_lifetime_and_claim_types_are_bounded(self):
        now = int(time.time())
        for changes in [{'iat':True}, {'exp':str(now+100)}, {'scope':['records:write']},
                        {'sub':''}, {'client_id':False}, {'jti':'x'*256}, {'exp':now+7200}, {'exp':now-1}]:
            with self.subTest(changes=changes), self.assertRaises(AuthenticationError):
                self.verifier.verify(self.token(self.claims(**changes)))

    def test_malformed_and_large_tokens_have_generic_errors(self):
        for token in (None, '', 'bad.token.input', 'x'*16385):
            with self.assertRaisesRegex(AuthenticationError, '^Access token rejected$'):
                self.verifier.verify(token)

    def test_key_rotation_requires_explicit_trusted_configuration(self):
        keys = {'test-key':self.key.public_key()}
        verifier = AccessTokenVerifier(issuer='https://identity.example.test', audience='omnixat-records', public_keys=keys)
        keys['test-key'] = self.other_key.public_key()
        self.assertEqual(verifier.verify(self.token()).subject, 'fictional-user')
        rotated = AccessTokenVerifier(issuer='https://identity.example.test', audience='omnixat-records',
                                      public_keys={'new-key':self.other_key.public_key()})
        with self.assertRaises(AuthenticationError):
            rotated.verify(self.token())

    def test_invalid_verifier_configuration_is_rejected(self):
        config = dict(issuer='https://identity.example.test', audience='omnixat-records',
                      public_keys={'test-key': self.key.public_key()})
        for changes in [{'issuer':'http://identity.example.test'}, {'issuer':'https://user:pass@example.test'},
                        {'audience':''}, {'public_keys':{}}, {'public_keys':{'key':'not-a-public-key'}},
                        {'max_lifetime':True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AccessTokenVerifier(**(config | changes))
