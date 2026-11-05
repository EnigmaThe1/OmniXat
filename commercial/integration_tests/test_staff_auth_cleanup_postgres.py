from secrets import token_bytes, token_urlsafe
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from test_postgres import PostgresFixture


class StaffAuthCleanupTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name, password = "cleanup_test_" + uuid4().hex, token_urlsafe(32)
        cls.maintenance_role = sql.Identifier(name)
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}")
                          .format(cls.maintenance_role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL("DROP OWNED BY {}").format(cls.maintenance_role))
            cls.admin.execute(sql.SQL("DROP ROLE {}").format(cls.maintenance_role))

        cls.addClassCleanup(cleanup)
        for grant in ("USAGE ON SCHEMA omnixat_staff_maintenance",
                      "EXECUTE ON FUNCTION omnixat_staff_maintenance.prune_expired(integer)"):
            cls.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(cls.maintenance_role))
        cls.maintenance = psycopg.connect(make_conninfo(cls.runtime_dsn, user=name, password=password),
                                          autocommit=True)
        cls.addClassCleanup(cls.maintenance.close)

    def setUp(self):
        self.owner.execute("DELETE FROM omnixat_staff_login.transactions")
        self.owner.execute("DELETE FROM omnixat_staff_session.sessions")
        self.member = uuid4()
        self.owner.execute("""
            INSERT INTO omnixat_staff.memberships(id,issuer,subject,role)
            VALUES (%s, 'https://fictional.example.invalid/realms/staff', %s, 'support')
        """, (self.member, str(self.member)))

    def seed(self, offset):
        attempt, session = token_bytes(32), token_bytes(32)
        self.owner.execute("""
            INSERT INTO omnixat_staff_login.transactions(state_key,browser_key,expires_at)
            VALUES (%s,%s,statement_timestamp() + %s * interval '1 second')
        """, (attempt, token_bytes(32), offset))
        self.owner.execute("""
            INSERT INTO omnixat_staff_session.sessions
                (token_digest,membership_id,issuer,subject,authenticated_at,expires_at)
            VALUES (%s,%s,'https://fictional.example.invalid/realms/staff',%s,1,
                    statement_timestamp() + %s * interval '1 second')
        """, (session, self.member, str(self.member), offset))
        return attempt, session

    def prune(self, size):
        return self.maintenance.execute(
            "SELECT * FROM omnixat_staff_maintenance.prune_expired(%s)", (size,)).fetchone()

    def remaining(self):
        return (
            self.owner.execute("SELECT state_key FROM omnixat_staff_login.transactions").fetchall(),
            self.owner.execute("SELECT token_digest FROM omnixat_staff_session.sessions").fetchall(),
        )

    def test_expired_rows_deleted_in_batches_without_touching_active_rows(self):
        self.seed(-120)
        newest = self.seed(0)
        active = self.seed(600)
        self.assertEqual(self.prune(1), (1, 1))
        for rows, recent_key, active_key in zip(self.remaining(), newest, active):
            self.assertCountEqual(rows, [(recent_key,), (active_key,)])
        self.assertEqual(self.prune(50), (1, 1))
        self.assertEqual(self.prune(50), (0, 0))
        self.assertEqual(self.remaining(), ([(active[0],)], [(active[1],)]))

    def test_locked_expired_rows_are_left_for_next_batch(self):
        locked = self.seed(-120)
        self.seed(-60)
        with self.owner.transaction():
            self.owner.execute("SELECT 1 FROM omnixat_staff_login.transactions WHERE state_key=%s FOR UPDATE",
                               (locked[0],)).fetchone()
            self.owner.execute("SELECT 1 FROM omnixat_staff_session.sessions WHERE token_digest=%s FOR UPDATE",
                               (locked[1],)).fetchone()
            self.assertEqual(self.prune(100), (1, 1))
            self.assertEqual(self.remaining(), ([(locked[0],)], [(locked[1],)]))
        self.assertEqual(self.prune(100), (1, 1))

    def test_direct_sql_cannot_request_unbounded_cleanup(self):
        self.owner.execute("""
            INSERT INTO omnixat_staff_login.transactions(state_key,browser_key,expires_at)
            SELECT decode(lpad(to_hex(i),64,'0'),'hex'),
                   decode(repeat('0',64),'hex'), statement_timestamp()
            FROM generate_series(1,501) AS i
        """)
        self.seed(-1)
        for invalid in (None, -1, 0):
            self.assertEqual(self.prune(invalid), (0, 0))
        self.assertEqual(self.prune(2147483647), (500, 1))
        self.assertEqual(self.prune(2147483647), (2, 0))

    def test_maintenance_login_gets_counts_without_direct_table_grants(self):
        self.seed(-60)
        for query in (
            "SELECT * FROM omnixat_staff_login.transactions",
            "SELECT * FROM omnixat_staff_session.sessions",
            "DELETE FROM omnixat_staff_session.sessions",
            "SELECT * FROM omnixat_staff.memberships",
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.maintenance.execute(query)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.runtime.execute("SELECT * FROM omnixat_staff_maintenance.prune_expired()")
        # Schema visibility alone must not permit execution.
        self.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_staff_maintenance TO {}")
                           .format(sql.Identifier(self.role)))
        try:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.runtime.execute("SELECT * FROM omnixat_staff_maintenance.prune_expired()")
        finally:
            self.owner.execute(sql.SQL("REVOKE USAGE ON SCHEMA omnixat_staff_maintenance FROM {}")
                               .format(sql.Identifier(self.role)))
        self.assertEqual(self.prune(1), (1, 1))
