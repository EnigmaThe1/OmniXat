"""Requires a disposable PostgreSQL cluster; creates/drops its own database/role.

OMNIXAT_TEST_ADMIN_DSN must point to a local test cluster with CREATEDB/CREATEROLE.
This suite fails clearly when absent; it is separate from dependency-free core tests.
"""
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import Principal
from omnixat_core.postgres import migrate, tenant_records


class PostgresFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ.get("OMNIXAT_TEST_ADMIN_DSN")
        if not dsn:
            raise RuntimeError("Set OMNIXAT_TEST_ADMIN_DSN to a disposable local PostgreSQL cluster")
        cls.admin = psycopg.connect(dsn, autocommit=True)
        cls.addClassCleanup(cls.admin.close)
        cls.database = "omnixat_test_" + uuid4().hex
        cls.role = "omnixat_test_" + uuid4().hex
        cls.admin.execute(sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(cls.database)))
        def cleanup_database():
            cls.admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(cls.database)))
            cls.admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(cls.role)))
        cls.addClassCleanup(cleanup_database)
        cls.owner = psycopg.connect(dsn, dbname=cls.database, autocommit=True)
        cls.addClassCleanup(cls.owner.close)
        migrate(cls.owner)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE").format(
            sql.Identifier(cls.role), sql.Literal(password)))
        cls.owner.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {} ").format(
            sql.Identifier(cls.database), sql.Identifier(cls.role)))
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat TO {} ").format(sql.Identifier(cls.role)))
        cls.owner.execute(sql.SQL("GRANT SELECT ON omnixat.tenants TO {} ").format(sql.Identifier(cls.role)))
        cls.owner.execute(sql.SQL("GRANT SELECT, INSERT ON omnixat.organisations, omnixat.notes, omnixat.record_creations TO {} ").format(sql.Identifier(cls.role)))
        cls.owner.execute(sql.SQL("GRANT SELECT ON omnixat.identities, omnixat.memberships TO {} ").format(sql.Identifier(cls.role)))
        cls.runtime_dsn = make_conninfo(dsn, dbname=cls.database, user=cls.role, password=password)
        cls.runtime = psycopg.connect(cls.runtime_dsn, autocommit=True)
        cls.addClassCleanup(cls.runtime.close)
        cls.owner.execute("SELECT version()")
        print("\nPostgreSQL integration:", cls.owner.execute("SHOW server_version").fetchone()[0])

    def setUp(self):
        self.a, self.b = str(uuid4()), str(uuid4())
        self.actor = Principal("fictional-editor", self.a, "editor")
        self.other = Principal("fictional-other", self.b, "editor")
        self.owner.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional A'),(%s,'Fictional B')",
                           (self.a, self.b))
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            self.org = records.create_organisation("Fictional organisation")["id"]
            self.note = records.create_note(self.org, "Fictional evidence note")["id"]


class PostgresRecordsTests(PostgresFixture):
    def test_persistence_after_reconnect(self):
        with psycopg.connect(self.runtime_dsn, autocommit=True) as db:
            with tenant_records(db, self.actor, self.a) as records:
                self.assertEqual(records.get_note(self.note)["created_by"], self.actor.user_id)

    def test_other_tenant_cannot_read_or_attach_note(self):
        with tenant_records(self.runtime, self.other, self.b, write=True) as records:
            with self.assertRaises(KeyError):
                records.get_organisation(self.org)
            with self.assertRaises(KeyError):
                records.get_note(self.note)
            with self.assertRaises(KeyError):
                records.create_note(self.org, "Forbidden")

    def test_wrong_membership_viewer_and_api_scope_denied(self):
        actors = [self.other, Principal("viewer", self.a, "viewer"),
                  Principal("api", self.a, "owner", api_scopes=frozenset({"records:read"})),
                  Principal("staff", None, staff_role="platform_owner", mfa_verified=True)]
        for actor in actors:
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                with tenant_records(self.runtime, actor, self.a, write=True):
                    self.fail("Must not enter")

    def test_read_only_unit_cannot_write(self):
        with tenant_records(self.runtime, self.actor, self.a) as records:
            with self.assertRaises(PermissionError):
                records.create_note(self.org, "Forbidden")

    def test_agent_can_prepare_note_with_attribution(self):
        agent = Principal("fictional-agent", self.a, "editor", actor_kind="agent")
        with tenant_records(self.runtime, agent, self.a, write=True) as records:
            self.assertEqual(records.create_note(self.org, "Prepared by agent")["created_by"], "fictional-agent")

    def test_rls_blocks_unscoped_sql_read(self):
        self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.organisations").fetchall(), [])
        self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.notes").fetchall(), [])
        self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.tenants").fetchall(), [])

    def test_rls_filters_queries_without_tenant_predicate(self):
        with tenant_records(self.runtime, self.other, self.b):
            self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.notes WHERE id=%s", (self.note,)).fetchall(), [])

    def test_rls_rejects_foreign_tenant_insert(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with tenant_records(self.runtime, self.actor, self.a, write=True):
                self.runtime.execute("""INSERT INTO omnixat.organisations VALUES
                    (%s,%s,'Forbidden','fictional',DEFAULT)""", (self.b, uuid4()))

    def test_composite_foreign_key_rejects_cross_tenant_reference(self):
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with tenant_records(self.runtime, self.other, self.b, write=True):
                self.runtime.execute("""INSERT INTO omnixat.notes VALUES
                    (%s,%s,%s,'Forbidden','fictional',DEFAULT)""", (self.b, uuid4(), self.org))

    def test_exception_rolls_back_and_clears_context(self):
        with self.assertRaisesRegex(RuntimeError, "Simulated"):
            with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
                org = records.create_organisation("Rollback")["id"]
                raise RuntimeError("Simulated interruption")
        with tenant_records(self.runtime, self.actor, self.a) as records:
            with self.assertRaises(KeyError):
                records.get_organisation(org)
        self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.notes").fetchall(), [])

    def test_connection_reuse_and_ended_repository(self):
        with tenant_records(self.runtime, self.actor, self.a) as old:
            old.get_note(self.note)
        with tenant_records(self.runtime, self.other, self.b):
            with self.assertRaises(RuntimeError):
                old.get_note(self.note)
        self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.notes").fetchall(), [])

    def test_nested_unit_is_rejected(self):
        with tenant_records(self.runtime, self.actor, self.a):
            with self.assertRaises(ValueError):
                with tenant_records(self.runtime, self.other, self.b):
                    self.fail("Nested tenant context")

    def test_superuser_and_owner_runtime_denied(self):
        with self.assertRaises(PermissionError):
            with tenant_records(self.owner, self.actor, self.a):
                self.fail("Privileged runtime")

    def test_runtime_cannot_change_schema_or_provision_tenant(self):
        for query in ["ALTER TABLE omnixat.notes DISABLE ROW LEVEL SECURITY",
                      "INSERT INTO omnixat.tenants VALUES (gen_random_uuid(),'Forbidden')",
                      "TRUNCATE omnixat.notes",
                      "CREATE TABLE omnixat.forbidden (id int)"]:
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.runtime.execute(query)

    def test_migration_repeat_and_checksum_guard(self):
        before = self.owner.execute("SELECT * FROM public.omnixat_schema_migrations").fetchall()
        migrate(self.owner)
        self.assertEqual(before, self.owner.execute("SELECT * FROM public.omnixat_schema_migrations").fetchall())
        self.owner.execute("UPDATE public.omnixat_schema_migrations SET digest='tampered'")
        try:
            with self.assertRaisesRegex(ValueError, "checksum"):
                migrate(self.owner)
        finally:
            for version, digest, _ in before:
                self.owner.execute("UPDATE public.omnixat_schema_migrations SET digest=%s WHERE version=%s", (digest, version))

    def test_blank_note_rejected_atomically(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
                records.create_note(self.org, "  ")

    def test_disabled_rls_is_rejected(self):
        self.owner.execute("ALTER TABLE omnixat.notes DISABLE ROW LEVEL SECURITY")
        try:
            with self.assertRaises(PermissionError):
                with tenant_records(self.runtime, self.actor, self.a):
                    self.fail("Unprotected table")
        finally:
            self.owner.execute("ALTER TABLE omnixat.notes ENABLE ROW LEVEL SECURITY")

    def test_non_superuser_table_owner_is_rejected(self):
        original = self.owner.execute("SELECT current_user").fetchone()[0]
        self.owner.execute(sql.SQL("ALTER TABLE omnixat.notes OWNER TO {}").format(sql.Identifier(self.role)))
        try:
            with self.assertRaises(PermissionError):
                with tenant_records(self.runtime, self.actor, self.a):
                    self.fail("Table owner runtime")
        finally:
            self.owner.execute(sql.SQL("ALTER TABLE omnixat.notes OWNER TO {}").format(sql.Identifier(original)))
            self.owner.execute(sql.SQL("GRANT SELECT, INSERT ON omnixat.notes TO {}").format(sql.Identifier(self.role)))

    def test_read_only_transaction_blocks_raw_write(self):
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            with tenant_records(self.runtime, self.actor, self.a):
                self.runtime.execute("INSERT INTO omnixat.organisations VALUES (%s,%s,'Forbidden','fictional',DEFAULT)",
                                     (self.a, uuid4()))

    def test_migration_failure_rolls_back_ddl_and_version(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from omnixat_core import postgres
        with TemporaryDirectory() as temp:
            path = Path(temp)
            for source in postgres.MIGRATIONS.glob('*.sql'):
                (path / source.name).write_bytes(source.read_bytes())
            (path / '9999_failure.sql').write_text(
                "CREATE TABLE omnixat.must_rollback (id int); SELECT 1/0;")
            with patch.object(postgres, 'MIGRATIONS', path):
                with self.assertRaises(psycopg.errors.DivisionByZero):
                    migrate(self.owner)
        self.assertIsNone(self.owner.execute("SELECT to_regclass('omnixat.must_rollback')").fetchone()[0])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM public.omnixat_schema_migrations").fetchone()[0], len(list(postgres.MIGRATIONS.glob("*.sql"))))

    def test_membership_of_table_owner_role_is_rejected(self):
        original = self.owner.execute("SELECT current_user").fetchone()[0]
        self.admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(original), sql.Identifier(self.role)))
        try:
            with self.assertRaises(PermissionError):
                with tenant_records(self.runtime, self.actor, self.a):
                    self.fail("Runtime can assume table owner")
        finally:
            self.admin.execute(sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(original), sql.Identifier(self.role)))

    def test_missing_migration_files_are_rejected(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from omnixat_core import postgres
        with TemporaryDirectory() as temp, patch.object(postgres, 'MIGRATIONS', Path(temp)):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                migrate(self.owner)

    def test_upgrade_from_first_schema_preserves_existing_records(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from omnixat_core import postgres
        database = 'omnixat_test_' + uuid4().hex
        self.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        try:
            with psycopg.connect(self.admin.info.dsn, dbname=database, autocommit=True) as owner:
                with TemporaryDirectory() as temp:
                    first = Path(temp)
                    source = postgres.MIGRATIONS / '0001_tenant_records.sql'
                    (first / source.name).write_bytes(source.read_bytes())
                    with patch.object(postgres,'MIGRATIONS',first):
                        migrate(owner)
                tenant,organisation = uuid4(),uuid4()
                owner.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional legacy tenant')",(tenant,))
                owner.execute("INSERT INTO omnixat.organisations VALUES (%s,%s,'Fictional legacy organisation','fixture',DEFAULT)",
                              (tenant,organisation))
                migrate(owner)
                self.assertEqual(owner.execute('SELECT id FROM omnixat.organisations').fetchall(),[(organisation,)])
                self.assertEqual(owner.execute('SELECT count(*) FROM public.omnixat_schema_migrations').fetchone()[0],10)
        finally:
            self.admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))

    def test_record_transaction_timeouts_are_local(self):
        before = self.runtime.execute("SELECT current_setting('statement_timeout'),current_setting('lock_timeout')").fetchone()
        with tenant_records(self.runtime,self.actor,self.a):
            values = self.runtime.execute("SELECT current_setting('statement_timeout'),current_setting('lock_timeout'),current_setting('idle_in_transaction_session_timeout')").fetchone()
            self.assertEqual(values,('5s','1s','5s'))
        self.assertEqual(self.runtime.execute("SELECT current_setting('statement_timeout'),current_setting('lock_timeout')").fetchone(),before)

    def test_query_timeout_rolls_back_and_allows_connection_reuse(self):
        with self.assertRaises(psycopg.errors.QueryCanceled):
            with tenant_records(self.runtime,self.actor,self.a,write=True) as records:
                org=records.create_organisation('Must roll back')['id']
                self.runtime.execute("SET LOCAL statement_timeout='10ms'")
                self.runtime.execute('SELECT pg_sleep(0.1)')
        with tenant_records(self.runtime,self.actor,self.a) as records:
            with self.assertRaises(KeyError):
                records.get_organisation(org)

    def test_elapsed_deadline_refuses_commit_and_rolls_back(self):
        from unittest.mock import patch
        with patch('omnixat_core.postgres.monotonic',side_effect=[0,11]):
            with self.assertRaises(TimeoutError):
                with tenant_records(self.runtime,self.actor,self.a,write=True) as records:
                    org=records.create_organisation('Commit deadline rollback')['id']
        with tenant_records(self.runtime,self.actor,self.a) as records:
            with self.assertRaises(KeyError):
                records.get_organisation(org)
