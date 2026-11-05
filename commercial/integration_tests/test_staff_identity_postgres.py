from time import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import require_staff, require_tenant
from omnixat_core.identity import AuthenticationError
from omnixat_core.staff_identity import StaffIDTokenVerifier
from omnixat_core.staff_identity_postgres import resolve_staff_login
from test_postgres import PostgresFixture


class StaffDirectoryFixture(PostgresFixture):
    issuer = "https://staff.example.invalid"
    nonce = "ab" * 32

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name, password = "staff_test_" + uuid4().hex, uuid4().hex
        cls.staff_role = sql.Identifier(name)
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}")
                          .format(cls.staff_role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL("DROP OWNED BY {}").format(cls.staff_role))
            cls.admin.execute(sql.SQL("DROP ROLE {}").format(cls.staff_role))

        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_staff TO {}").format(cls.staff_role))
        cls.owner.execute(sql.SQL("GRANT SELECT ON omnixat_staff.memberships TO {}").format(cls.staff_role))
        cls.directory = psycopg.connect(make_conninfo(cls.runtime_dsn, user=name, password=password),
                                        autocommit=True)
        cls.addClassCleanup(cls.directory.close)
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.verifier = StaffIDTokenVerifier(issuer=cls.issuer, client_id="staff",
                                           public_keys={"test": cls.key.public_key()}, mfa_acr="urn:example:mfa")

    def setUp(self):
        super().setUp()
        self.staff_id, self.subject = uuid4(), str(uuid4())
        self.now = int(time())
        self.claims = dict(iss=self.issuer, sub=self.subject, aud="staff", iat=self.now,
                           exp=self.now + 60, auth_time=self.now - 10, nonce=self.nonce,
                           acr="urn:example:mfa", role="platform_owner")

    def provision(self, role="platform_owner"):
        self.owner.execute("INSERT INTO omnixat_staff.memberships(id, issuer, subject, role) VALUES (%s,%s,%s,%s)",
                           (self.staff_id, self.issuer, self.subject, role))

    def resolve(self, connection=None, **claims):
        token = jwt.encode(self.claims | claims, self.key, algorithm="RS256", headers={"kid": "test"})
        return resolve_staff_login(self.directory if connection is None else connection,
                                   self.verifier, token, expected_nonce=self.nonce)


class StaffIdentityPostgresTests(StaffDirectoryFixture):
    def test_signed_login_without_staff_membership_cannot_self_enrol(self):
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",
                           (self.staff_id, self.issuer, self.subject))
        with self.assertRaises(AuthenticationError):
            self.resolve()

    def test_role_is_current_and_does_not_grant_tenant_access(self):
        self.provision()
        actor = self.resolve()
        self.assertEqual(actor.user_id, str(self.staff_id))
        require_staff(actor, "sandbox-metrics:read")
        with self.assertRaises(PermissionError):
            require_tenant(actor, self.a, "records:read")
        self.owner.execute("UPDATE omnixat_staff.memberships SET role='support' WHERE id=%s", (self.staff_id,))
        with self.assertRaises(PermissionError):
            require_staff(self.resolve(), "sandbox-metrics:read")

    def test_revocation_and_reauthentication_cutoff(self):
        self.provision()
        self.owner.execute("UPDATE omnixat_staff.memberships SET auth_valid_after=%s WHERE id=%s",
                           (self.claims["auth_time"], self.staff_id))
        with self.assertRaises(AuthenticationError):
            self.resolve(iat=self.now)
        self.assertEqual(self.resolve(auth_time=self.now).staff_role, "platform_owner")
        self.owner.execute("UPDATE omnixat_staff.memberships SET revoked_at=now() WHERE id=%s", (self.staff_id,))
        with self.assertRaises(AuthenticationError):
            self.resolve(auth_time=self.now)

    def test_directory_login_is_read_only_and_scope_cleared(self):
        self.provision()
        self.resolve()
        self.assertEqual(self.directory.execute("SELECT id FROM omnixat_staff.memberships").fetchall(), [])
        for db, query in (
            (self.directory, "UPDATE omnixat_staff.memberships SET revoked_at=NULL"),
            (self.directory, "SELECT * FROM omnixat.notes"),
            (self.directory, "SELECT * FROM omnixat_metrics.sandbox_snapshot"),
            (self.runtime, "SELECT * FROM omnixat_staff.memberships"),
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute(query)

    def test_resolver_rejects_overprivileged_login(self):
        self.provision()
        with self.assertRaises(PermissionError):
            self.resolve(connection=self.owner)
        self.owner.execute(sql.SQL("GRANT UPDATE (role) ON omnixat_staff.memberships TO {}").format(self.staff_role))
        try:
            with self.assertRaises(PermissionError):
                self.resolve()
        finally:
            self.owner.execute(sql.SQL("REVOKE UPDATE (role) ON omnixat_staff.memberships FROM {}").format(self.staff_role))
