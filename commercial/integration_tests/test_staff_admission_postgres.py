from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from secrets import token_bytes, token_urlsafe
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient

from omnixat_core.staff_admission_postgres import PostgresStaffAdmission
from omnixat_core.staff_browser import create_staff_browser_app
from test_postgres import PostgresFixture


class StaffAdmissionTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name, password = "staff_admit_test_" + uuid4().hex, token_urlsafe(32)
        role = sql.Identifier(name)
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL("DROP OWNED BY {}").format(role))
            cls.admin.execute(sql.SQL("DROP ROLE {}").format(role))

        cls.addClassCleanup(cleanup)
        for grant in ("USAGE ON SCHEMA omnixat_staff_admission",
                      "EXECUTE ON FUNCTION omnixat_staff_admission.admit(text,text)"):
            cls.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(role))
        cls.admission_dsn = make_conninfo(cls.runtime_dsn, user=name, password=password)

    def setUp(self):
        self.owner.execute("""
            UPDATE omnixat_staff_admission.budgets
            SET minute_id=-1, admitted=0, sources='{}', total_limit=60 WHERE action='login'
        """)
        self.owner.execute("""
            UPDATE omnixat_staff_admission.budgets
            SET minute_id=-1, admitted=0, sources='{}' WHERE action<>'login'
        """)
        self.key = token_bytes(32)
        self.admit = PostgresStaffAdmission(self.connect, key=self.key)

    def connect(self):
        return psycopg.connect(self.admission_dsn, autocommit=True)

    @staticmethod
    def request(host, **headers):
        return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)

    def stable_minute(self, work):
        # Tests that assert a whole fixed-minute budget retry only if they
        # straddled the real database minute boundary.
        query = "SELECT floor(extract(epoch FROM clock_timestamp()) / 60)::bigint"
        for _ in range(2):
            self.owner.execute("UPDATE omnixat_staff_admission.budgets "
                               "SET minute_id=-1, admitted=0, sources='{}'")
            start = self.owner.execute(query).fetchone()
            result = work()
            if self.owner.execute(query).fetchone() == start:
                return result
        self.fail("Could not test within one database minute")

    def test_concurrent_workers_cannot_exceed_one_source_budget(self):
        def work():
            ready = Barrier(9, timeout=10)

            def attempt():
                admission = PostgresStaffAdmission(self.connect, key=self.key)
                ready.wait()
                return admission(self.request("192.0.2.10"), "login")

            with ThreadPoolExecutor(max_workers=9) as pool:
                futures = [pool.submit(attempt) for _ in range(9)]
                return [future.result(timeout=15) for future in futures]

        self.assertCountEqual(self.stable_minute(work), [True] * 5 + [False] * 4)

    def test_source_limit_does_not_consume_other_sources_or_other_action_budget(self):
        self.owner.execute("UPDATE omnixat_staff_admission.budgets SET total_limit=6 WHERE action='login'")

        def work():
            one = self.request("192.0.2.10")
            results = [self.admit(one, "login") for _ in range(7)]
            results.extend((self.admit(self.request("192.0.2.11"), "login"),
                            self.admit(self.request("192.0.2.12"), "login"),
                            self.admit(one, "logout")))
            return results

        self.assertEqual(self.stable_minute(work), [True] * 5 + [False, False, True, False, True])

    def test_new_window_replaces_old_counters_and_future_window_fails_closed(self):
        self.owner.execute("""
            UPDATE omnixat_staff_admission.budgets
            SET minute_id=floor(extract(epoch FROM clock_timestamp()) / 60)::bigint - 1,
                admitted=60, sources='{"previous":60}' WHERE action='login'
        """)
        self.assertTrue(self.admit(self.request("192.0.2.10"), "login"))
        count, sources = self.owner.execute("""
            SELECT admitted,sources FROM omnixat_staff_admission.budgets WHERE action='login'
        """).fetchone()
        self.assertEqual(count, 1)
        self.assertEqual(list(sources.values()), [1])
        self.assertNotIn("192.0.2.10", repr(sources))
        self.owner.execute("UPDATE omnixat_staff_admission.budgets SET minute_id=minute_id+10 WHERE action='login'")
        self.assertFalse(self.admit(self.request("192.0.2.10"), "login"))

    def test_ipv6_prefix_and_ipv4_mapped_addresses_cannot_rotate_source(self):
        def work():
            return ([self.admit(self.request("2001:db8:1:2::" + str(i)), "login") for i in range(1, 7)],
                    [self.admit(self.request(host), "login") for host in
                     (["192.0.2.7", "::ffff:192.0.2.7"] * 3)])

        self.assertEqual(self.stable_minute(work), ([True] * 5 + [False], [True] * 5 + [False]))

    def test_ungranted_roles_and_direct_table_access_fail(self):
        with self.connect() as db:
            for query in ("SELECT * FROM omnixat_staff_admission.budgets",
                          "UPDATE omnixat_staff_admission.budgets SET admitted=0",
                          "SELECT * FROM omnixat_staff_session.sessions"):
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute(query)
            self.assertFalse(db.execute("SELECT omnixat_staff_admission.admit('unknown',%s)",
                                        ("0" * 64,)).fetchone()[0])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.runtime.execute("SELECT omnixat_staff_admission.admit('login',%s)", ("0" * 64,))
        no_db = Mock(side_effect=AssertionError("Must not connect"))
        hook = PostgresStaffAdmission(no_db, key=self.key)
        self.assertFalse(hook(self.request("not-an-ip", forwarded="for=192.0.2.9"), "login"))
        self.assertFalse(hook(SimpleNamespace(client=None), "login"))
        no_db.assert_not_called()

    def test_browser_returns_429_before_provider_work_and_ignores_forwarded_headers(self):
        origin = "https://staff.example.invalid"
        provider = Mock(redirect_uri=origin + "/staff/login/callback")
        provider.begin.return_value = "https://provider.example.invalid/realms/fictional/auth"
        app = create_staff_browser_app(origin=origin, provider=provider, attempts=lambda: nullcontext(None),
                                       sessions=lambda: nullcontext(None), directory=lambda: nullcontext(None),
                                       admit=self.admit)

        def work():
            provider.reset_mock()
            with TestClient(app, base_url=origin, follow_redirects=False, client=("192.0.2.10", 12345)) as client:
                return [client.post("/staff/login", headers={
                    "origin": origin, "forwarded": f"for=192.0.2.{i}",
                    "x-forwarded-for": f"192.0.2.{i}",
                }).status_code for i in range(20, 26)]

        self.assertEqual(self.stable_minute(work), [303] * 5 + [429])
        self.assertEqual(provider.begin.call_count, 5)
