import time
from uuid import UUID, uuid4

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

from test_postgres import PostgresFixture
from omnixat_core.access import require_tenant, require_staff
from omnixat_core.identity import AccessTokenVerifier, AuthenticationError
from omnixat_core.identity_postgres import authenticated_records


class MembershipRecordsTests(PostgresFixture):
    def setUp(self):
        super().setUp()
        self.user = uuid4()
        self.subject = 'fictional-' + uuid4().hex
        self.issuer = 'https://identity.example.test'
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.verifier = AccessTokenVerifier(issuer=self.issuer, audience='omnixat-records',
                                          public_keys={'fictional':self.key.public_key()})
        self.iat = int(time.time()) - 1
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",
                           (self.user,self.issuer,self.subject))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.a,self.user))

    def token(self, **changes):
        claims = dict(iss=self.issuer,aud='omnixat-records',sub=self.subject,iat=self.iat,
                      exp=int(time.time())+300,jti=uuid4().hex,client_id='fictional-app',scope='records:read records:write')
        return jwt.encode(claims | changes,self.key,algorithm='RS256',headers={'kid':'fictional','typ':'at+jwt'})

    def records(self, *, tenant=None, write=False, token=None, connection=None):
        return authenticated_records(connection or self.runtime,self.verifier,token or self.token(),tenant or self.a,write=write)

    def test_signed_identity_resolves_persisted_member_and_attributes_note(self):
        with self.records(write=True) as records:
            note = records.create_note(self.org,'Fictional authenticated note')
            self.assertEqual(note['created_by'],str(self.user))
        with self.records() as records:
            self.assertEqual(records.get_note(note['id'])['body'],'Fictional authenticated note')

    def test_cross_tenant_and_unknown_identity_are_denied(self):
        for tenant,token in [(self.b,self.token()),(self.a,self.token(sub='unknown'))]:
            with self.assertRaises(AuthenticationError):
                with self.records(tenant=tenant,token=token):
                    self.fail('Unauthorised membership')

    def test_roles_come_from_database_not_token(self):
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        with self.assertRaises(PermissionError):
            with self.records(write=True,token=self.token(role='owner',tenant_role='owner',staff_role='platform_owner')):
                self.fail('Claim must not elevate viewer')
        with self.records() as records:
            self.assertEqual(records.get_organisation(self.org)['id'],self.org)

    def test_token_scopes_limit_membership(self):
        with self.assertRaises(PermissionError):
            with self.records(write=True,token=self.token(scope='records:read')):
                self.fail('Missing write scope')

    def test_membership_revocation_rejects_same_unexpired_token(self):
        token = self.token()
        with self.records(token=token) as records:
            records.get_organisation(self.org)
        self.owner.execute("UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s",(self.user,))
        with self.assertRaises(AuthenticationError):
            with self.records(token=token):
                self.fail('Revoked membership')

    def test_disabled_identity_and_token_cutoff_reject_access(self):
        for assignment in ('disabled_at=now()', 'disabled_at=NULL, tokens_valid_after='+str(self.iat)):
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            with self.assertRaises(AuthenticationError):
                with self.records():
                    self.fail('Identity revoked or token too old')

    def test_multi_tenant_memberships_have_independent_roles_and_revocation(self):
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'viewer')",(self.b,self.user))
        with self.records(tenant=self.b):
            self.assertEqual(self.runtime.execute('SELECT tenant_id FROM omnixat.memberships').fetchall(),[(UUID(self.b),)])
        self.owner.execute("UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s",(self.b,self.user))
        with self.records() as records:
            records.get_organisation(self.org)
        with self.assertRaises(AuthenticationError):
            with self.records(tenant=self.b):
                self.fail('Other membership revoked')

    def test_identity_context_clears_on_reuse_and_failure(self):
        with self.records():
            self.assertEqual(len(self.runtime.execute('SELECT id FROM omnixat.identities').fetchall()),1)
        self.assertEqual(self.runtime.execute('SELECT id FROM omnixat.identities').fetchall(),[])
        self.assertEqual(self.runtime.execute('SELECT user_id FROM omnixat.memberships').fetchall(),[])
        with self.assertRaises(AuthenticationError):
            with self.records(token=self.token(sub='unknown')):
                pass
        self.assertEqual(self.runtime.execute('SELECT id FROM omnixat.identities').fetchall(),[])

    def test_runtime_cannot_self_enrol_or_change_identity(self):
        for query in ['UPDATE omnixat.memberships SET role=\'owner\'',
                      'UPDATE omnixat.identities SET actor_kind=\'human\'',
                      'DELETE FROM omnixat.memberships',
                      'INSERT INTO omnixat.memberships VALUES (gen_random_uuid(),gen_random_uuid(),\'owner\',NULL)']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.runtime.execute(query)

    def test_agent_kind_cannot_be_overridden_and_bearer_cannot_approve(self):
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.memberships SET role='owner' WHERE user_id=%s",(self.user,))
        with self.records(token=self.token(actor_kind='human',mfa_verified=True,staff_role='platform_owner',
                                          scope='records:read records:write filings:approve members:manage')) as records:
            actor = records._actor
            self.assertEqual(actor.actor_kind,'agent')
            self.assertFalse(actor.mfa_verified)
            self.assertIsNone(actor.staff_role)
            with self.assertRaises(PermissionError):
                require_tenant(actor,self.a,'filings:approve')
            with self.assertRaises(PermissionError):
                require_staff(actor,'metrics:read')

    def test_membership_state_persists_across_new_connections(self):
        with psycopg.connect(self.runtime_dsn,autocommit=True) as connection:
            with self.records(connection=connection) as records:
                self.assertEqual(records.get_organisation(self.org)['id'],self.org)

    def test_disabled_membership_rls_is_rejected(self):
        self.owner.execute('ALTER TABLE omnixat.memberships DISABLE ROW LEVEL SECURITY')
        try:
            with self.assertRaises(PermissionError):
                with self.records():
                    self.fail('Unprotected membership lookup')
        finally:
            self.owner.execute('ALTER TABLE omnixat.memberships ENABLE ROW LEVEL SECURITY')

    def test_human_owner_bearer_still_cannot_approve_or_administer(self):
        self.owner.execute("UPDATE omnixat.memberships SET role='owner' WHERE user_id=%s",(self.user,))
        with self.records(token=self.token(scope='records:read filings:approve billing:manage members:manage',
                                          mfa_verified=True,staff_role='platform_owner')) as records:
            actor = records._actor
            self.assertEqual(actor.actor_kind,'human')
            for permission in ('filings:approve','billing:manage','members:manage'):
                with self.assertRaises(PermissionError):
                    require_tenant(actor,self.a,permission)

    def test_role_downgrade_is_observed_without_reissuing_token(self):
        token = self.token()
        with self.records(write=True,token=token) as records:
            records.create_note(self.org,'Before downgrade')
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        with self.assertRaises(PermissionError):
            with self.records(write=True,token=token):
                self.fail('Cached role')
