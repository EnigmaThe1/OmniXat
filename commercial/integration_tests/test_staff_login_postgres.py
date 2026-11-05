from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from secrets import token_bytes, token_urlsafe
from threading import Barrier
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.identity import AuthenticationError
from omnixat_core.staff_login_postgres import PostgresStaffLoginTransactions
from test_postgres import PostgresFixture


class StaffLoginTransactionTests(PostgresFixture):
    profile = dict(issuer="https://staff.example.invalid", client_id="fictional-staff",
                   redirect_uri="https://app.example.invalid/admin/login/callback")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name, password = "staff_login_test_" + token_bytes(16).hex(), token_bytes(16).hex()
        cls.login_role = sql.Identifier(name)
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}")
                          .format(cls.login_role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL("DROP OWNED BY {}").format(cls.login_role))
            cls.admin.execute(sql.SQL("DROP ROLE {}").format(cls.login_role))

        cls.addClassCleanup(cleanup)
        for grant in (
            "USAGE ON SCHEMA omnixat_staff_login",
            "SELECT, DELETE ON omnixat_staff_login.transactions",
            "INSERT (state_key, browser_key) ON omnixat_staff_login.transactions",
        ):
            cls.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(cls.login_role))
        cls.login_dsn = make_conninfo(cls.runtime_dsn, user=name, password=password)
        cls.login = psycopg.connect(cls.login_dsn, autocommit=True)
        cls.addClassCleanup(cls.login.close)

    def setUp(self):
        self.owner.execute("DELETE FROM omnixat_staff_login.transactions")
        self.key = token_bytes(32)
        self.store = PostgresStaffLoginTransactions(**self.profile, key=self.key)
        self.browser = token_urlsafe(32)

    def begin(self):
        return self.store.begin(self.login, browser_binding=self.browser)

    def consume(self, start):
        return self.store.consume(self.login, state=start.state, browser_binding=self.browser)

    def test_separate_process_can_recover_pkce_and_nonce_from_bound_state(self):
        start = self.begin()
        same_config = PostgresStaffLoginTransactions(**self.profile, key=self.key)
        with psycopg.connect(self.login_dsn, autocommit=True) as connection:
            material = same_config.consume(connection, state=start.state, browser_binding=self.browser)
        challenge = urlsafe_b64encode(sha256(material.code_verifier.encode("ascii")).digest()).decode().rstrip("=")
        self.assertEqual(start.code_challenge, challenge)
        self.assertEqual(start.nonce, material.nonce)
        self.assertRegex(start.nonce, r"^[0-9a-f]{64}$")
        self.assertRegex(material.code_verifier, r"^[A-Za-z0-9_-]{43}$")
        self.assertNotIn(material.code_verifier, repr(material))
        self.assertNotIn(start.state, repr(start))
        with self.assertRaises(AuthenticationError):
            self.consume(start)

    def test_wrong_browser_profile_or_server_key_cannot_consume(self):
        start = self.begin()
        with self.assertRaises(AuthenticationError):
            self.store.consume(self.login, state=start.state, browser_binding=token_urlsafe(32))
        for change in (
            {"issuer": "https://other.example.invalid"},
            {"client_id": "other-client"},
            {"redirect_uri": "https://app.example.invalid/other"},
            {"key": token_bytes(32)},
        ):
            with self.subTest(change=list(change)), self.assertRaises(AuthenticationError):
                other = PostgresStaffLoginTransactions(**((self.profile | {"key": self.key}) | change))
                other.consume(self.login, state=start.state, browser_binding=self.browser)
        self.assertEqual(self.consume(start).nonce, start.nonce)

    def test_database_stores_only_derived_keys_and_expiry(self):
        start = self.begin()
        rows = self.login.execute("SELECT state_key, browser_key, expires_at > clock_timestamp() "
                                  "FROM omnixat_staff_login.transactions").fetchall()
        [(state_key, browser_key, unexpired)] = rows
        self.assertTrue(unexpired)
        self.assertEqual(len(state_key), 32)
        self.assertEqual(len(browser_key), 32)
        self.assertNotEqual(state_key, browser_key)
        self.assertNotIn(start.state.encode(), state_key + browser_key)
        self.assertNotIn(self.browser.encode(), state_key + browser_key)
        self.assertNotEqual(bytes.fromhex(start.nonce), state_key)
        self.assertNotEqual(bytes.fromhex(start.nonce), browser_key)

    def test_expired_login_denied_and_deleted(self):
        start = self.begin()
        self.owner.execute("UPDATE omnixat_staff_login.transactions SET expires_at = clock_timestamp()")
        with self.assertRaises(AuthenticationError):
            self.consume(start)
        self.assertEqual(self.login.execute("SELECT count(*) FROM omnixat_staff_login.transactions").fetchone(), (0,))

    def test_concurrent_callback_only_one_can_consume(self):
        start = self.begin()
        ready = Barrier(2, timeout=5)

        def attempt():
            with psycopg.connect(self.login_dsn, autocommit=True) as connection:
                ready.wait()
                try:
                    return self.store.consume(connection, state=start.state, browser_binding=self.browser).nonce
                except AuthenticationError:
                    return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            self.assertCountEqual([f.result(timeout=10) for f in futures], [start.nonce, None])

    def test_uncommitted_consumption_cannot_escape_outer_transaction(self):
        start = self.begin()
        with self.login.transaction():
            with self.assertRaises(ValueError):
                self.consume(start)
        self.assertEqual(self.consume(start).nonce, start.nonce)

    def test_runtime_grants_are_separate_and_expiry_is_database_owned(self):
        for db, query in (
            (self.login, "SELECT * FROM omnixat_staff.memberships"),
            (self.login, "SELECT * FROM omnixat.notes"),
            (self.login, "UPDATE omnixat_staff_login.transactions SET expires_at=now()"),
            (self.login, "INSERT INTO omnixat_staff_login.transactions(expires_at) VALUES (now())"),
            (self.runtime, "SELECT * FROM omnixat_staff_login.transactions"),
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute(query)
        for db in (self.owner, self.runtime):
            with self.assertRaises(PermissionError):
                self.store.begin(db, browser_binding=self.browser)
        self.owner.execute(sql.SQL("GRANT INSERT (expires_at) ON omnixat_staff_login.transactions TO {}")
                           .format(self.login_role))
        try:
            with self.assertRaises(PermissionError):
                self.begin()
        finally:
            self.owner.execute(sql.SQL("REVOKE INSERT (expires_at) ON omnixat_staff_login.transactions FROM {}")
                               .format(self.login_role))

    def test_failed_insert_does_not_return_a_second_login(self):
        state = token_urlsafe(32)
        with patch("omnixat_core.staff_login_postgres.token_urlsafe", return_value=state):
            start = self.begin()
            with self.assertRaises(psycopg.errors.UniqueViolation):
                self.begin()
        self.assertEqual(self.consume(start).nonce, start.nonce)
