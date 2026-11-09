"""Operational migration failures against disposable PostgreSQL, never mocks."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

from test_postgres import PostgresFixture
from omnixat_core import postgres


class MigrationExecutionTests(PostgresFixture):
    def history(self):
        return self.owner.execute(
            'SELECT version,digest,applied_at FROM public.omnixat_schema_migrations ORDER BY version'
        ).fetchall()

    def settings(self):
        return self.owner.execute(
            "SELECT current_setting('lock_timeout'),current_setting('statement_timeout')"
        ).fetchone()

    def test_competing_migrator_times_out_then_retries_without_session_leak(self):
        before, settings = self.history(), self.settings()
        with psycopg.connect(self.owner.info.dsn, autocommit=True) as blocker:
            with blocker.transaction():
                blocker.execute('SELECT pg_advisory_xact_lock(724190026)')
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    postgres.migrate(self.owner, lock_timeout_ms=100, statement_timeout_ms=2000)
                self.assertEqual(self.owner.info.transaction_status, TransactionStatus.IDLE)
                self.assertEqual(self.history(), before)
                self.assertEqual(self.settings(), settings)
        postgres.migrate(self.owner)
        self.assertEqual(self.history(), before)
        self.assertEqual(self.settings(), settings)

    def test_table_lock_contention_rolls_back_and_releases_advisory_lock(self):
        before, settings = self.history(), self.settings()
        with psycopg.connect(self.owner.info.dsn, autocommit=True) as blocker:
            with blocker.transaction():
                blocker.execute('LOCK TABLE public.omnixat_schema_migrations IN ACCESS EXCLUSIVE MODE')
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    postgres.migrate(self.owner, lock_timeout_ms=100, statement_timeout_ms=2000)
                self.assertTrue(blocker.execute('SELECT pg_try_advisory_xact_lock(724190026)').fetchone()[0])
        self.assertEqual(self.history(), before)
        self.assertEqual(self.settings(), settings)
        postgres.migrate(self.owner)

    def test_statement_timeout_rolls_back_ddl_and_receipt_then_retry_succeeds(self):
        before, settings = self.history(), self.settings()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for source in postgres.MIGRATIONS.glob('*.sql'):
                (root / source.name).write_bytes(source.read_bytes())
            pending = root / '9999_execution_bound.sql'
            pending.write_text('CREATE TABLE omnixat.migration_bound_fixture(id int); SELECT pg_sleep(1);')
            with patch.object(postgres, 'MIGRATIONS', root):
                with self.assertRaises(psycopg.errors.QueryCanceled):
                    postgres.migrate(self.owner, lock_timeout_ms=50, statement_timeout_ms=100)
                self.assertEqual(self.history(), before)
                self.assertIsNone(self.owner.execute(
                    "SELECT to_regclass('omnixat.migration_bound_fixture')").fetchone()[0])
                self.assertEqual(self.settings(), settings)
                # Change only never-applied SQL; applied migrations remain immutable.
                pending.write_text('CREATE TABLE omnixat.migration_bound_fixture(id int);')
                try:
                    postgres.migrate(self.owner)
                    self.assertEqual(len(self.history()), len(before) + 1)
                    self.assertIsNotNone(self.owner.execute(
                        "SELECT to_regclass('omnixat.migration_bound_fixture')").fetchone()[0])
                finally:
                    self.owner.execute('DROP TABLE IF EXISTS omnixat.migration_bound_fixture')
                    self.owner.execute('DELETE FROM public.omnixat_schema_migrations WHERE version=%s', (pending.name,))
        self.assertEqual(self.settings(), settings)

    def test_gap_in_history_is_rejected_before_pending_sql(self):
        before = self.history()
        version, digest, applied_at = before[0]
        self.owner.execute('DELETE FROM public.omnixat_schema_migrations WHERE version=%s', (version,))
        try:
            with self.assertRaisesRegex(ValueError, 'contiguous prefix'):
                postgres.migrate(self.owner)
            # The original table and all later migration receipts still exist.
            self.assertIsNotNone(self.owner.execute("SELECT to_regclass('omnixat.tenants')").fetchone()[0])
            self.assertEqual(len(self.history()), len(before) - 1)
        finally:
            self.owner.execute('INSERT INTO public.omnixat_schema_migrations VALUES (%s,%s,%s)',
                               (version, digest, applied_at))
        postgres.migrate(self.owner)
        self.assertEqual(self.history(), before)

    def test_invalid_timeouts_do_not_start_transaction(self):
        for values in [(0, 100), (True, 100), (1, False), (1, '100'), (1.5, 100),
                       (100, 100), (101, 100), (1, 3_600_001), (-1, 100)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                postgres.migrate(self.owner, lock_timeout_ms=values[0], statement_timeout_ms=values[1])
            self.assertEqual(self.owner.info.transaction_status, TransactionStatus.IDLE)

    def test_complete_schema_migrates_under_constrained_database_owner(self):
        role, database = 'omnixat_migrator_' + uuid4().hex, 'omnixat_test_' + uuid4().hex
        password = uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE').format(
            sql.Identifier(role), sql.Literal(password)))
        try:
            self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database), sql.Identifier(role)))
            try:
                with psycopg.connect(self.admin.info.dsn, dbname=database, user=role,
                                     password=password, autocommit=True) as owner:
                    self.assertEqual(owner.execute(
                        'SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user'
                    ).fetchone(), (False, False, False, False))
                    postgres.migrate(owner)
                    postgres.migrate(owner)
                    self.assertEqual(owner.execute('SELECT count(*) FROM public.omnixat_schema_migrations').fetchone()[0],
                                     len(list(postgres.MIGRATIONS.glob('*.sql'))))
                    self.assertEqual(owner.execute(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='omnixat' AND c.relkind='r' AND (NOT relrowsecurity OR NOT relforcerowsecurity)"
                    ).fetchone()[0], 0)
            finally:
                self.admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(database)))
        finally:
            self.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
