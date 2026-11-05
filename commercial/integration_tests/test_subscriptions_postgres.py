from datetime import datetime, timedelta, timezone
import hmac
import json
from secrets import token_bytes
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import Principal
from omnixat_core.sandbox_events import SandboxEventReceiver, SandboxEventConflict, SandboxEventRejected
from omnixat_core.subscriptions_postgres import PostgresSubscriptionSandbox, SandboxSubscriptionConflict
from test_postgres import PostgresFixture


class SubscriptionSandboxTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sandbox_dsn = cls.sandbox_login(receipts=False)
        cls.sandbox = psycopg.connect(cls.sandbox_dsn, autocommit=True)
        cls.addClassCleanup(cls.sandbox.close)
        cls.event_dsn = cls.sandbox_login(receipts=True)
        cls.events = psycopg.connect(cls.event_dsn, autocommit=True)
        cls.addClassCleanup(cls.events.close)

    @classmethod
    def sandbox_login(cls, *, receipts):
        role_name = 'sandbox_test_' + uuid4().hex
        role = sql.Identifier(role_name)
        password = uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(role))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(role))

        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_sandbox TO {}').format(role))
        cls.owner.execute(sql.SQL('GRANT SELECT ON omnixat_sandbox.price_terms, omnixat_sandbox.subscriptions, omnixat_sandbox.cancellations TO {}').format(role))
        tables = ('omnixat_sandbox.event_receipts' if receipts else
                  'omnixat_sandbox.subscriptions, omnixat_sandbox.cancellations')
        cls.owner.execute(sql.SQL('GRANT SELECT, INSERT ON ' + tables + ' TO {}').format(role))
        return make_conninfo(cls.runtime_dsn, user=role_name, password=password)

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

    def simulated_event(self, sub, **overrides):
        fields = dict(tenant_id=str(sub.tenant_id), event_id=str(uuid4()),
                      subscription_id=str(sub.id), price_version_id=str(sub.price_version_id),
                      state=sub.state)
        return json.dumps(fields | overrides).encode()

    def signed(self, receiver, key, body, *, timestamp=None):
        ts = int(self.at.timestamp()) if timestamp is None else timestamp
        signature = hmac.digest(key, b"omnixat:sandbox:subscription-snapshot:v1:" +
                                str(ts).encode("ascii") + b"." + body, "sha256").hex()
        return receiver.accept(body, timestamp=ts, signature=signature)

    def test_signed_event_persists_and_replays_original_reconciliation(self):
        self.price()
        sub = self.start()
        key = token_bytes(32)
        body = self.simulated_event(sub)
        receiver = SandboxEventReceiver(self.events, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        first = self.signed(receiver, key, body)
        self.assertEqual((first.outcome, first.observed_state), ("matched", "trialing"))
        self.at = sub.trial_ends_at
        with psycopg.connect(self.event_dsn, autocommit=True) as connection:
            fresh = SandboxEventReceiver(connection, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
            self.assertEqual(self.signed(fresh, key, body), first)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat_sandbox.event_receipts WHERE tenant_id=%s",
                                            (self.a,)).fetchone(), (1,))

    def test_changed_body_with_same_event_id_conflicts(self):
        self.price()
        sub = self.start()
        key = token_bytes(32)
        receiver = SandboxEventReceiver(self.events, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        event = str(uuid4())
        first = self.simulated_event(sub, event_id=event)
        self.signed(receiver, key, first)
        with self.assertRaises(SandboxEventConflict):
            self.signed(receiver, key, self.simulated_event(sub, event_id=event, state="active"))
        self.assertEqual(self.signed(receiver, key, first).outcome, "matched")

    def test_invalid_signature_stale_timestamp_and_ambiguous_json_fail_before_db(self):
        key = token_bytes(32)
        receiver = SandboxEventReceiver(None, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        with self.assertRaises(SandboxEventRejected):
            self.signed(receiver, token_bytes(32), b'{}')
        for offset in (-301, 301, 10**1000):
            with self.assertRaises(SandboxEventRejected):
                self.signed(receiver, key, b'{}', timestamp=int(self.at.timestamp()) + offset)
        for body in (b'{"state":"pending","state":"active"}', b'{'*2049, b'\xff', b'[]'):
            with self.assertRaises(SandboxEventRejected):
                self.signed(receiver, key, body)

    def test_simulated_active_and_price_mismatch_do_not_modify_subscription(self):
        self.price(days=0)
        sub = self.start()
        key = token_bytes(32)
        receiver = SandboxEventReceiver(self.events, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        state = self.signed(receiver, key, self.simulated_event(sub, state="active"))
        price = self.signed(receiver, key, self.simulated_event(sub, price_version_id=str(uuid4())))
        self.assertEqual((state.outcome, price.outcome), ("state_mismatch", "price_mismatch"))
        self.assertEqual(self.service.get(self.member, self.a), sub)

    def test_signed_event_cannot_cross_receiver_tenant_or_target_other_subscription(self):
        self.price()
        sub = self.start()
        other = self.service.start(self.other_member, self.b, plan=self.plan, interval='month')
        key = token_bytes(32)
        receiver = SandboxEventReceiver(self.events, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        for body in (self.simulated_event(other), self.simulated_event(sub, subscription_id=str(other.id))):
            with self.assertRaises(SandboxEventRejected):
                self.signed(receiver, key, body)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat_sandbox.event_receipts WHERE tenant_id IN (%s,%s)",
                                            (self.a, self.b)).fetchone(), (0,))

    def test_event_receipt_is_tenant_scoped_and_append_only(self):
        self.price()
        sub = self.start()
        key = token_bytes(32)
        receiver = SandboxEventReceiver(self.events, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        self.signed(receiver, key, self.simulated_event(sub))
        self.assertEqual(self.events.execute('SELECT * FROM omnixat_sandbox.event_receipts').fetchall(), [])
        with self.events.transaction():
            self.events.execute("SELECT set_config('omnixat.tenant_id', %s, true)", (self.b,))
            self.assertEqual(self.events.execute('SELECT * FROM omnixat_sandbox.event_receipts').fetchall(), [])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.events.execute('DELETE FROM omnixat_sandbox.event_receipts')

    def test_receiver_rejects_subscription_writer_database_role(self):
        self.price()
        sub = self.start()
        key = token_bytes(32)
        receiver = SandboxEventReceiver(self.sandbox, tenant_id=self.a, signing_key=key, clock=lambda: self.at)
        with self.assertRaises(PermissionError):
            self.signed(receiver, key, self.simulated_event(sub))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.events.execute("INSERT INTO omnixat_sandbox.cancellations VALUES (%s,%s,%s,%s)",
                                (self.a, sub.id, self.at, "fixture"))
