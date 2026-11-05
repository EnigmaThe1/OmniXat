from dataclasses import replace
from datetime import timedelta
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql

from omnixat_core.access import Principal
from omnixat_core.postgres import migrate
from omnixat_core.sandbox_metrics import SandboxMetrics, read_sandbox_metrics


class SandboxMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ["OMNIXAT_TEST_ADMIN_DSN"]
        cls.admin = psycopg.connect(dsn, autocommit=True)
        cls.addClassCleanup(cls.admin.close)

        def login():
            name, password = "metrics_test_" + uuid4().hex, uuid4().hex
            role = sql.Identifier(name)
            cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
            cls.addClassCleanup(cls.admin.execute, sql.SQL("DROP ROLE {}").format(role))
            return name, password

        owner_login, metrics_login, sandbox_login = login(), login(), login()
        database_name = "metrics_test_" + uuid4().hex
        database = sql.Identifier(database_name)
        cls.admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(database, sql.Identifier(owner_login[0])))
        cls.addClassCleanup(cls.admin.execute, sql.SQL("DROP DATABASE {} WITH (FORCE)").format(database))

        def connect(login):
            db = psycopg.connect(dsn, dbname=database_name, user=login[0],
                                 password=login[1], autocommit=True)
            cls.addClassCleanup(db.close)
            return db

        cls.owner, cls.metrics, cls.sandbox = map(connect, (owner_login, metrics_login, sandbox_login))
        # Migrate with a non-superuser, non-BYPASSRLS owner so the view really
        # depends on the new SELECT policies.
        migrate(cls.owner)
        cls.metrics_role = sql.Identifier(metrics_login[0])
        sandbox_role = sql.Identifier(sandbox_login[0])
        for grant in ("USAGE ON SCHEMA omnixat_metrics", "SELECT ON omnixat_metrics.sandbox_snapshot"):
            cls.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(cls.metrics_role))
        for grant in ("USAGE ON SCHEMA omnixat_sandbox", "SELECT ON ALL TABLES IN SCHEMA omnixat_sandbox"):
            cls.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(sandbox_role))

        cls.staff = Principal("fictional-owner", None, staff_role="platform_owner", mfa_verified=True)
        cls.now = cls.owner.execute("SELECT statement_timestamp()").fetchone()[0]
        cls.day = timedelta(days=1)

    def test_empty_snapshot(self):
        # This test's data is empty regardless of the test order: the seeded
        # scenario rolls back or removes its fixture rows.
        result = read_sandbox_metrics(self.metrics, self.staff)
        self.assertEqual(result, SandboxMetrics(result.observed_at, 0, 0, 0, 0, 0, 0, 0))

    def test_fixed_aggregate_across_tenants_and_cutoffs(self):
        now, day = self.now, self.day
        past, future, price = now - day, now + day, uuid4()
        self.owner.execute("INSERT INTO omnixat_billing.plans(code,display_name,created_by) "
                           "VALUES ('fictional','Fictional','fixture')")
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_billing.plans")
        self.owner.execute("""INSERT INTO omnixat_billing.price_versions
            (id,plan,amount_minor,currency,interval,trial_days,api_allowance,effective_at,created_by)
            VALUES (%s,'fictional',1000,'GBP','month',7,0,%s,'fixture')""", (price, past))
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_billing.price_versions")

        def scoped_delete(tenant):
            with self.owner.transaction():
                self.owner.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (str(tenant),))
                for table in ("event_receipts", "cancellations", "subscriptions"):
                    self.owner.execute(sql.SQL("DELETE FROM omnixat_sandbox.{} WHERE tenant_id=%s")
                                       .format(sql.Identifier(table)), (tenant,))
                self.owner.execute("DELETE FROM omnixat.tenants WHERE id=%s", (tenant,))

        tenants = []
        shared_event_id = uuid4()
        for started, expiry, cancelled, outcomes in (
            (past, None, future, [("matched", past), ("price_mismatch", past)]),
            (past, future, None, [("state_mismatch", past), ("matched", future)]),
            (past, now, None, []),
            (past, now, past, []),
            (future, None, None, []),
        ):
            tenant, subscription = uuid4(), uuid4()
            tenants.append(tenant)
            with self.owner.transaction():
                self.owner.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (str(tenant),))
                self.owner.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional tenant')", (tenant,))
                self.owner.execute("INSERT INTO omnixat_sandbox.subscriptions VALUES (%s,%s,%s,%s,%s,'fixture')",
                                   (tenant, subscription, price, started, expiry))
                if cancelled:
                    self.owner.execute("INSERT INTO omnixat_sandbox.cancellations VALUES (%s,%s,%s,'fixture')",
                                       (tenant, subscription, cancelled))
                for i, (outcome, received) in enumerate(outcomes):
                    self.owner.execute("""INSERT INTO omnixat_sandbox.event_receipts
                        VALUES (%s,%s,%s,%s,%s,'pending','pending',%s,%s)""",
                                       (tenant, shared_event_id if i == 0 else uuid4(),
                                        subscription, bytes(32), price, outcome, received))
            self.addCleanup(scoped_delete, tenant)

        result = read_sandbox_metrics(self.metrics, self.staff)
        self.assertGreaterEqual(result.observed_at, now)
        self.assertEqual(result, SandboxMetrics(result.observed_at, 1, 1, 1, 1, 1, 1, 1))
        self.assertEqual(self.sandbox.execute("SELECT count(*) FROM omnixat_sandbox.subscriptions").fetchone(), (0,))
        with self.sandbox.transaction():
            self.sandbox.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (str(tenants[0]),))
            self.assertEqual(self.sandbox.execute("SELECT tenant_id FROM omnixat_sandbox.subscriptions").fetchall(),
                             [(tenants[0],)])

    def test_requires_separate_interactive_platform_owner(self):
        for changes in (
            {"staff_role": "billing_admin"}, {"staff_role": "supervisor"},
            {"staff_role": "support"}, {"staff_role": None}, {"mfa_verified": False},
            {"actor_kind": "agent"}, {"api_scopes": frozenset({"sandbox-metrics:read"})},
            {"tenant_id": str(uuid4())}, {"tenant_role": "owner"},
        ):
            with self.subTest(changes=changes), self.assertRaises(PermissionError):
                # No connection is required to reject an unauthorized actor.
                read_sandbox_metrics(None, replace(self.staff, **changes))

    def test_login_cannot_read_source_tables_or_write_projection(self):
        for query in (
            "SELECT * FROM omnixat_sandbox.event_receipts",
            "SELECT * FROM omnixat_sandbox.subscriptions",
            "SELECT * FROM omnixat_sandbox.cancellations",
            "SELECT * FROM omnixat_billing.price_versions",
            "SELECT * FROM omnixat.notes",
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.metrics.execute(query)
        self.assertEqual(self.metrics.execute(
            "SELECT has_table_privilege('omnixat_metrics.sandbox_snapshot', 'DELETE')").fetchone(), (False,))
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.metrics.execute("DELETE FROM omnixat_metrics.sandbox_snapshot")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.sandbox.execute("SELECT * FROM omnixat_metrics.sandbox_snapshot")

    def test_service_rejects_overprivileged_or_ungranted_login(self):
        for db in (self.owner, self.sandbox):
            with self.subTest(user=db.info.user), self.assertRaises(PermissionError):
                read_sandbox_metrics(db, self.staff)
        self.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_sandbox TO {}").format(self.metrics_role))
        try:
            with self.assertRaises(PermissionError):
                read_sandbox_metrics(self.metrics, self.staff)
        finally:
            self.owner.execute(sql.SQL("REVOKE USAGE ON SCHEMA omnixat_sandbox FROM {}").format(self.metrics_role))
