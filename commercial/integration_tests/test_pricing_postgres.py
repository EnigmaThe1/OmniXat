from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import Principal
from omnixat_core.pricing_postgres import PostgresPriceCatalogue
from test_postgres import PostgresFixture


class PricingPostgresTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pricing_role = 'omnixat_pricing_test_' + uuid4().hex
        identifier = sql.Identifier(cls.pricing_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE').format(
            identifier, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(identifier))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(identifier))

        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_billing TO {}').format(identifier))
        cls.owner.execute(sql.SQL('GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA omnixat_billing TO {}').format(identifier))
        cls.pricing_dsn = make_conninfo(cls.runtime_dsn, user=cls.pricing_role, password=password)
        cls.pricing = psycopg.connect(cls.pricing_dsn, autocommit=True)
        cls.addClassCleanup(cls.pricing.close)

    def setUp(self):
        self.catalogue = PostgresPriceCatalogue(self.pricing)
        self.staff = Principal('fictional-owner', None, staff_role='platform_owner', mfa_verified=True)
        self.admin_staff = Principal('fictional-billing', None, staff_role='billing_admin', mfa_verified=True)
        self.plan = 'test-' + uuid4().hex
        self.start = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.catalogue.register_plan(self.staff, code=self.plan, display_name='Fictional plan')

    def create(self, actor=None, **overrides):
        values = dict(plan=self.plan, amount_minor=1200, interval='month', trial_days=14,
                      api_allowance=100, effective_at=self.start)
        return self.catalogue.create(actor or self.staff, **(values | overrides))

    def test_scheduled_versions_keep_old_reference_across_connections(self):
        old = self.create()
        future = self.start + timedelta(days=30)
        new = self.create(self.admin_staff, amount_minor=1700, trial_days=7, effective_at=future)
        annual = self.create(interval='year', amount_minor=12000)
        with psycopg.connect(self.pricing_dsn, autocommit=True) as connection:
            restored = PostgresPriceCatalogue(connection)
            self.assertEqual(restored.get(self.staff, old.id), old)
            self.assertEqual(restored.effective(self.staff, plan=self.plan, interval='month', as_of=future-timedelta(microseconds=1)), old)
            self.assertEqual(restored.effective(self.staff, plan=self.plan, interval='month', as_of=future), new)
            self.assertEqual(restored.effective(self.staff, plan=self.plan, interval='year', as_of=future), annual)
            with self.assertRaises(KeyError):
                restored.effective(self.staff, plan=self.plan, interval='month', as_of=self.start-timedelta(seconds=1))

    def test_equal_instant_conflicts_without_overwriting_price_or_audit(self):
        old = self.create()
        equivalent = self.start.astimezone(timezone(timedelta(hours=2)))
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.create(amount_minor=9999, effective_at=equivalent)
        self.assertEqual(self.catalogue.get(self.staff, old.id), old)
        events = self.catalogue.audit(self.staff, plan=self.plan)
        self.assertEqual([event['operation'] for event in events], ['price_version_created', 'plan_registered'])
        self.assertEqual(events[0]['result_id'], old.id)

    def test_owner_audit_has_minimal_attribution_and_is_bounded(self):
        price = self.create(self.admin_staff)
        event, = self.catalogue.audit(self.staff, plan=self.plan, limit=1)
        self.assertEqual(set(event), {'operation', 'result_id', 'created_by', 'created_at'})
        self.assertEqual((event['result_id'], event['created_by']), (price.id, self.admin_staff.user_id))
        with self.assertRaises(PermissionError):
            self.catalogue.audit(self.admin_staff, plan=self.plan)
        with self.assertRaises(ValueError):
            self.catalogue.audit(self.staff, plan=self.plan, limit=101)

    def test_no_customer_api_agent_or_unverified_principal_can_write(self):
        for actor in (
            Principal('customer', 'fictional-tenant', tenant_role='owner', mfa_verified=True),
            Principal('mixed', 'fictional-tenant', staff_role='platform_owner', mfa_verified=True),
            Principal('api', None, staff_role='platform_owner', mfa_verified=True, api_scopes=frozenset({'prices:write'})),
            Principal('agent', None, staff_role='platform_owner', mfa_verified=True, actor_kind='agent'),
            Principal('staff', None, staff_role='platform_owner'),
            Principal('supervisor', None, staff_role='supervisor', mfa_verified=True),
        ):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                self.create(actor)
        self.assertEqual(len(self.catalogue.audit(self.staff, plan=self.plan)), 1)

    def test_db_roles_have_separate_access_and_no_repricing_privilege(self):
        price = self.create()
        for conn, query in (
            (self.pricing, 'SELECT * FROM omnixat.notes'),
            (self.pricing, 'UPDATE omnixat_billing.price_versions SET amount_minor=0'),
            (self.pricing, 'DELETE FROM omnixat_billing.price_versions'),
            (self.runtime, 'SELECT * FROM omnixat_billing.price_versions'),
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute(query)
        self.assertEqual(self.catalogue.get(self.staff, price.id), price)

    def test_service_rejects_owner_customer_and_overprivileged_connections(self):
        for conn in (self.owner, self.runtime):
            with self.assertRaises(PermissionError):
                PostgresPriceCatalogue(conn).audit(self.staff, plan=self.plan)
        identifier = sql.Identifier(self.pricing_role)
        self.owner.execute(sql.SQL('GRANT UPDATE (amount_minor) ON omnixat_billing.price_versions TO {}').format(identifier))
        try:
            with self.assertRaises(PermissionError):
                self.catalogue.audit(self.staff, plan=self.plan)
        finally:
            self.owner.execute(sql.SQL('REVOKE UPDATE (amount_minor) ON omnixat_billing.price_versions FROM {}').format(identifier))

    def test_invalid_money_time_and_missing_plan_leave_no_price_event(self):
        for kwargs in ({'amount_minor': 12.5}, {'amount_minor': True}, {'amount_minor': 2**63},
                       {'trial_days': -1}, {'effective_at': self.start.replace(tzinfo=None)}):
            with self.subTest(values=kwargs), self.assertRaises(ValueError):
                self.create(**kwargs)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.create(plan='absent-' + uuid4().hex)
        self.assertEqual([x['operation'] for x in self.catalogue.audit(self.staff, plan=self.plan)], ['plan_registered'])

    def test_existing_plan_cannot_be_replaced_by_registration(self):
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.catalogue.register_plan(self.staff, code=self.plan, display_name='Changed plan')
        row = self.pricing.execute('SELECT display_name FROM omnixat_billing.plans WHERE code=%s', (self.plan,)).fetchone()
        self.assertEqual(row, ('Fictional plan',))
