from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import Principal
from omnixat_core.subscriptions_postgres import PostgresSubscriptionSandbox, SandboxSubscriptionConflict
from test_postgres import PostgresFixture


class SubscriptionSandboxTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        role_name = 'sandbox_test_' + uuid4().hex
        role = sql.Identifier(role_name)
        password = uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(role))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(role))

        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_sandbox TO {}').format(role))
        cls.owner.execute(sql.SQL('GRANT SELECT ON omnixat_sandbox.price_terms TO {}').format(role))
        cls.owner.execute(sql.SQL('GRANT SELECT, INSERT ON omnixat_sandbox.subscriptions, omnixat_sandbox.cancellations TO {}').format(role))
        cls.sandbox_dsn = make_conninfo(cls.runtime_dsn, user=role_name, password=password)
        cls.sandbox = psycopg.connect(cls.sandbox_dsn, autocommit=True)
        cls.addClassCleanup(cls.sandbox.close)

    def setUp(self):
        super().setUp()
        self.member = Principal('fictional-owner-a', self.a, 'owner', mfa_verified=True)
        self.other_member = Principal('fictional-owner-b', self.b, 'owner', mfa_verified=True)
        self.at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.service = PostgresSubscriptionSandbox(self.sandbox, clock=lambda: self.at)
        self.plan = 'fictional-' + uuid4().hex
        self.owner.execute("""INSERT INTO omnixat_billing.plans(code,display_name,created_by)
            VALUES (%s,'Fictional plan','fixture')""", (self.plan,))

    def price(self, days=7, *, at=None, amount=1200, interval='month'):
        version = uuid4()
        self.owner.execute("""INSERT INTO omnixat_billing.price_versions
            (id,plan,amount_minor,currency,interval,trial_days,api_allowance,effective_at,created_by)
            VALUES (%s,%s,%s,'GBP',%s,%s,20,%s,'fixture')""",
                           (version, self.plan, amount, interval, days, at or self.at))
        return version

    def start(self):
        return self.service.start(self.member, self.a, plan=self.plan, interval='month')

    def test_pinned_price_survives_reprice_and_reconnect(self):
        old = self.price()
        sub = self.start()
        self.at += timedelta(days=1)
        new = self.price(days=2, amount=2500)
        other = self.service.start(self.other_member, self.b, plan=self.plan, interval='month')
        self.assertEqual(other.price_version_id, new)
        with psycopg.connect(self.sandbox_dsn, autocommit=True) as db:
            saved = PostgresSubscriptionSandbox(db, clock=lambda: self.at).get(self.member, self.a)
        self.assertEqual(saved, sub)
        self.assertEqual((saved.price_version_id, saved.amount_minor), (old, 1200))

    def test_trial_expires_at_deadline_without_activation_or_reset(self):
        self.price(days=2)
        sub = self.start()
        self.assertEqual(sub.trial_ends_at, self.at + timedelta(days=2))
        self.at = sub.trial_ends_at - timedelta(microseconds=1)
        self.assertEqual(self.service.get(self.member, self.a).state, 'trialing')
        self.at = sub.trial_ends_at
        self.assertEqual(self.service.get(self.member, self.a).state, 'trial_expired')
        with self.assertRaises(SandboxSubscriptionConflict):
            self.service.cancel(self.member, self.a)
        with self.assertRaises(SandboxSubscriptionConflict):
            self.start()

    def test_no_trial_is_pending_and_cancellation_replays(self):
        self.price(days=0)
        sub = self.start()
        self.assertEqual((sub.state, sub.trial_ends_at), ('pending', None))
        self.at += timedelta(hours=1)
        cancelled = self.service.cancel(self.member, self.a)
        self.assertEqual((cancelled.state, cancelled.cancelled_at), ('cancelled', self.at))
        self.at += timedelta(days=10)
        self.assertEqual(self.service.cancel(self.member, self.a), cancelled)
        self.assertEqual(self.owner.execute("""SELECT cancelled_by FROM omnixat_sandbox.cancellations
            WHERE tenant_id=%s""", (self.a,)).fetchall(), [(self.member.user_id,)])

    def test_cancelled_trial_remains_cancelled_after_trial_deadline(self):
        self.price()
        sub = self.start()
        self.service.cancel(self.member, self.a)
        self.at = sub.trial_ends_at
        self.assertEqual(self.service.get(self.member, self.a).state, 'cancelled')

    def test_future_price_or_other_interval_does_not_start_subscription(self):
        self.price(at=self.at + timedelta(seconds=1))
        self.price(interval='year')
        with self.assertRaises(KeyError):
            self.start()
        with self.assertRaises(KeyError):
            self.service.get(self.member, self.a)
        self.at += timedelta(seconds=1)
        self.assertEqual(self.start().state, 'trialing')

    def test_agent_bearer_editor_unverified_and_cross_tenant_requests_denied(self):
        self.price()
        for actor in (
            self.other_member,
            Principal('editor', self.a, 'editor', mfa_verified=True),
            Principal('owner', self.a, 'owner'),
            Principal('agent', self.a, 'owner', mfa_verified=True, actor_kind='agent'),
            Principal('bearer', self.a, 'owner', mfa_verified=True, api_scopes=frozenset({'billing:manage'})),
        ):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                self.service.start(actor, self.a, plan=self.plan, interval='month')
        with self.assertRaises(KeyError):
            self.service.get(self.member, self.a)

    def test_sandbox_runtime_rls_and_minimal_grants(self):
        self.price()
        self.start()
        self.assertEqual(self.sandbox.execute('SELECT * FROM omnixat_sandbox.subscriptions').fetchall(), [])
        with self.sandbox.transaction():
            self.sandbox.execute("SELECT set_config('omnixat.tenant_id', %s, true)", (self.b,))
            self.assertEqual(self.sandbox.execute('SELECT * FROM omnixat_sandbox.subscriptions').fetchall(), [])
        for connection, query in (
            (self.sandbox, 'SELECT * FROM omnixat.notes'),
            (self.sandbox, 'SELECT created_by FROM omnixat_billing.price_versions'),
            (self.sandbox, 'UPDATE omnixat_sandbox.subscriptions SET started_by=\'changed\''),
            (self.sandbox, 'DELETE FROM omnixat_sandbox.cancellations'),
            (self.runtime, 'SELECT * FROM omnixat_sandbox.subscriptions'),
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(query)
        for connection in (self.runtime, self.owner):
            with self.assertRaises(PermissionError):
                PostgresSubscriptionSandbox(connection).get(self.member, self.a)

    def test_cancellation_fk_cannot_target_other_tenants_subscription(self):
        self.price()
        sub = self.start()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.sandbox.transaction():
                self.sandbox.execute("SELECT set_config('omnixat.tenant_id', %s, true)", (self.b,))
                self.sandbox.execute("""INSERT INTO omnixat_sandbox.cancellations
                    VALUES (%s,%s,%s,%s)""", (self.b, sub.id, self.at, self.other_member.user_id))
        self.assertEqual(self.service.get(self.member, self.a).state, 'trialing')
