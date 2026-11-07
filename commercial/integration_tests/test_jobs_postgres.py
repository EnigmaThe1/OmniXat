"""PostgreSQL job contract with fictional reference-only payloads and checkpoints."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import Principal
from omnixat_core.jobs_postgres import PostgresJobStore
from omnixat_core.postgres import MIGRATIONS, migrate
from test_postgres import PostgresFixture


class PostgresJobsTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job_role = cls.role + "_jobs"
        role = sql.Identifier(cls.job_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
                          .format(role, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_job_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat TO {}").format(role))
        cls.owner.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE ON omnixat.agent_jobs TO {}").format(role))
        cls.job_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database, user=cls.job_role, password=password)

    @classmethod
    def drop_job_role(cls):
        cls.owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(cls.job_role)))
        cls.admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.job_role)))

    def setUp(self):
        super().setUp()
        self.worker = Principal("fictional-agent", self.a, "editor", actor_kind="agent")
        self.job_connection = psycopg.connect(self.job_dsn, autocommit=True)
        self.addCleanup(self.job_connection.close)
        self.store = PostgresJobStore(self.job_connection)
        self.payload = {"evidence_ids": ["fictional-reference"]}

    def create(self):
        return self.store.create(self.worker, self.a, "fictional-batch", self.payload)

    def expire(self, job):
        self.owner.execute("""UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp() - interval '1 second'
            WHERE tenant_id=%s AND id=%s
        """, (self.a, job))

    def test_job_creation_and_progress_survive_reconnect_and_complete(self):
        job = self.create()
        self.assertEqual(self.store.get(self.worker, self.a, job), {"id": job, "status": "queued", "checkpoint": {}})
        token = self.store.claim(self.worker, self.a, job, lease_seconds=120)
        self.store.checkpoint(self.worker, self.a, job, token, {"step": "matched", "entry_ids": ["fictional-entry"]})
        with psycopg.connect(self.job_dsn, autocommit=True) as connection:
            restored = PostgresJobStore(connection)
            self.assertEqual(restored.get(self.worker, self.a, job)["checkpoint"],
                             {"step": "matched", "entry_ids": ["fictional-entry"]})
            restored.checkpoint(self.worker, self.a, job, token, {"step": "prepared"}, complete=True)
        self.assertEqual(self.store.get(self.worker, self.a, job),
                         {"id": job, "status": "completed", "checkpoint": {"step": "prepared"}})
        self.assertEqual(self.owner.execute("""
            SELECT created_by,claimed_by,lease_token,lease_until FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        """, (self.a, job)).fetchone(), (self.worker.user_id, self.worker.user_id, None, None))
        with self.assertRaises(ValueError):
            self.store.claim(self.worker, self.a, job)
        with self.assertRaises(ValueError):
            self.store.checkpoint(self.worker, self.a, job, token, {"step": "late"})

    def test_job_creation_replays_concurrently_and_preserves_original_attribution(self):
        start = Barrier(2)
        def create():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                return PostgresJobStore(connection).create(self.worker, self.a, "fictional-batch", self.payload)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: create(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.store.create(self.actor, self.a, "fictional-batch", self.payload), first)
        with self.assertRaisesRegex(ValueError, "Idempotency key reused"):
            self.store.create(self.worker, self.a, "fictional-batch", {"evidence_ids": ["different-reference"]})
        self.assertEqual(self.owner.execute("SELECT id,created_by FROM omnixat.agent_jobs WHERE tenant_id=%s",
                                           (self.a,)).fetchall(), [(UUID(first), self.worker.user_id)])

    def test_competing_payloads_and_claims_have_one_winner(self):
        start = Barrier(2)
        def create(index):
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                try:
                    return PostgresJobStore(connection).create(self.worker, self.a, "fictional-race", {"reference": index})
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(create, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        job = next(result for result in results if result is not None)
        start = Barrier(2)
        def claim():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                try:
                    return PostgresJobStore(connection).claim(self.worker, self.a, job)
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            tokens = list(workers.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(token is not None for token in tokens), 1)

    def test_expired_and_replaced_workers_cannot_overwrite_or_complete(self):
        job = self.create()
        old = self.store.claim(self.worker, self.a, job)
        self.expire(job)
        with self.assertRaises(ValueError):
            self.store.checkpoint(self.worker, self.a, job, old, {"step": "expired"}, complete=True)
        replacement = Principal("fictional-replacement-agent", self.a, "editor", actor_kind="agent")
        new = self.store.claim(replacement, self.a, job)
        self.assertNotEqual(new, old)
        for actor, token in ((self.worker, old), (self.worker, new), (replacement, old)):
            with self.subTest(actor=actor.user_id, token=token), self.assertRaises(ValueError):
                self.store.checkpoint(actor, self.a, job, token, {"step": "stale"}, complete=True)
        self.store.checkpoint(replacement, self.a, job, new, {"step": "current"}, complete=True)
        self.assertEqual(self.store.get(replacement, self.a, job)["checkpoint"], {"step": "current"})

    def test_cross_tenant_access_and_request_keys_are_isolated(self):
        job = self.create()
        other_job = self.store.create(self.other, self.b, "fictional-batch", self.payload)
        self.assertNotEqual(job, other_job)
        with self.assertRaises(KeyError):
            self.store.get(self.other, self.b, job)
        with self.assertRaises(ValueError):
            self.store.claim(self.other, self.b, job)
        token = self.store.claim(self.worker, self.a, job)
        with self.assertRaises(ValueError):
            self.store.checkpoint(self.other, self.b, job, token, {})
        with self.assertRaises(PermissionError):
            self.store.get(self.other, self.a, job)
        self.assertEqual(self.job_connection.execute("SELECT * FROM omnixat.agent_jobs").fetchall(), [])
        with self.job_connection.transaction():
            self.job_connection.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.b,))
            self.assertEqual(self.job_connection.execute("SELECT id FROM omnixat.agent_jobs").fetchall(),
                             [(UUID(other_job),)])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.job_connection.transaction():
                self.job_connection.execute("""INSERT INTO omnixat.agent_jobs
                    (tenant_id,request_key,payload_hash,created_by) VALUES (%s,'forbidden',%s,'fictional')
                """, (self.a, bytes(32)))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.job_connection.execute("DELETE FROM omnixat.agent_jobs")

    def test_permission_matrix_and_privileged_connections_are_rejected(self):
        job = self.create()
        viewer = Principal("fictional-viewer", self.a, "viewer")
        self.assertEqual(self.store.get(viewer, self.a, job)["status"], "queued")
        token = self.store.claim(self.worker, self.a, job)
        for actor in (
            viewer, Principal("api", self.a, "editor", api_scopes=frozenset({"records:read"})),
            Principal("staff", self.a, "editor", staff_role="platform_owner", mfa_verified=True),
        ):
            for action in (
                lambda: self.store.create(actor, self.a, "forbidden", {}),
                lambda: self.store.claim(actor, self.a, job),
                lambda: self.store.checkpoint(actor, self.a, job, token, {}),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    action()
        with self.assertRaises(PermissionError):
            PostgresJobStore(self.owner).get(self.worker, self.a, job)
        with self.assertRaises(ValueError), self.job_connection.transaction():
            self.store.get(self.worker, self.a, job)

    def test_invalid_inputs_leave_job_unchanged(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        for key in ("", " ", "x" * 201, "bad\0key", None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.create(self.worker, self.a, key, {})
        with self.assertRaises(ValueError):
            self.store.create(self.worker, self.a, "bad-payload", {"value": float('nan')})
        for seconds in (0, 3601, True, 1.5):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                self.store.claim(self.worker, self.a, job, lease_seconds=seconds)
        for progress, complete in (([], False), ({"reference": "x" * 65536}, False), ({"value": float('nan')}, False), ({}, 1)):
            with self.subTest(complete=complete), self.assertRaises(ValueError):
                self.store.checkpoint(self.worker, self.a, job, token, progress, complete=complete)
        self.assertEqual(self.store.get(self.worker, self.a, job)["checkpoint"], {})
        self.store.checkpoint(self.worker, self.a, job, token, {"step": "valid"})

    def test_checkpoint_database_failure_rolls_back_and_releases_connection(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        with self.assertRaises(psycopg.errors.UntranslatableCharacter):
            self.store.checkpoint(self.worker, self.a, job, token, {"reference": "bad\0value"}, complete=True)
        self.assertEqual(self.store.get(self.worker, self.a, job), {"id": job, "status": "running", "checkpoint": {}})
        self.store.checkpoint(self.worker, self.a, job, token, {"step": "recovered"}, complete=True)

    def test_database_rejects_invalid_job_state(self):
        job = self.create()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute("UPDATE omnixat.agent_jobs SET status='running' WHERE tenant_id=%s AND id=%s", (self.a, job))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute("UPDATE omnixat.agent_jobs SET checkpoint='[]'::jsonb WHERE tenant_id=%s AND id=%s", (self.a, job))
        self.assertEqual(self.store.get(self.worker, self.a, job)["status"], "queued")


    def test_lock_wait_cannot_extend_expired_checkpoint_authority(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        self.owner.execute("""UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp() + interval '500 milliseconds'
            WHERE tenant_id=%s AND id=%s
        """, (self.a, job))
        started = Event()
        with psycopg.connect(self.job_dsn, autocommit=True) as connection, ThreadPoolExecutor(max_workers=1) as workers:
            def checkpoint():
                started.set()
                PostgresJobStore(connection).checkpoint(self.worker, self.a, job, token, {"step": "expired"}, complete=True)
            with self.owner.transaction():
                self.owner.execute("SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                   (self.a, job)).fetchone()
                result = workers.submit(checkpoint)
                self.assertTrue(started.wait(timeout=2))
                self.admin.execute("SELECT pg_sleep(0.6)")
                self.assertFalse(result.done())
            with self.assertRaises(ValueError):
                result.result(timeout=3)
        self.assertEqual(self.store.get(self.worker, self.a, job), {"id": job, "status": "running", "checkpoint": {}})


    def test_cancel_queued_job_replays_first_receipt_and_preserves_creation_key(self):
        job = self.create()
        first = self.store.cancel(self.actor, self.a, job)
        self.assertEqual((first.job_id, first.cancelled_by), (job, self.actor.user_id))
        with psycopg.connect(self.job_dsn, autocommit=True) as connection:
            restored = PostgresJobStore(connection)
            self.assertEqual(restored.cancel(self.worker, self.a, job), first)
            self.assertEqual(restored.get(self.worker, self.a, job),
                             {"id": job, "status": "cancelled", "checkpoint": {}})
        self.assertEqual(self.create(), job)
        with self.assertRaises(ValueError):
            self.store.claim(self.worker, self.a, job)
        self.assertEqual(self.owner.execute("""
            SELECT lease_token,lease_until,claimed_by,created_by FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        """, (self.a, job)).fetchone(), (None, None, None, self.worker.user_id))

    def test_cancel_running_job_preserves_progress_and_fences_active_worker(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        progress = {"step": "matched", "entry_ids": ["fictional-entry"]}
        self.store.checkpoint(self.worker, self.a, job, token, progress)
        receipt = self.store.cancel(self.actor, self.a, job)
        self.assertEqual(self.store.get(self.actor, self.a, job),
                         {"id": job, "status": "cancelled", "checkpoint": progress})
        for complete in (False, True):
            with self.subTest(complete=complete), self.assertRaises(ValueError):
                self.store.checkpoint(self.worker, self.a, job, token, {"step": "late"}, complete=complete)
        with self.assertRaises(ValueError):
            self.store.claim(self.worker, self.a, job)
        self.assertEqual(self.owner.execute("""
            SELECT lease_token,lease_until,claimed_by,cancelled_by,cancelled_at
            FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        """, (self.a, job)).fetchone(),
                         (None, None, self.worker.user_id, self.actor.user_id, receipt.cancelled_at))

    def test_concurrent_cancellations_preserve_one_attributed_receipt(self):
        job = self.create()
        start = Barrier(2)
        def cancel(actor):
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                return PostgresJobStore(connection).cancel(actor, self.a, job)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(cancel, (self.actor, self.worker)))
        self.assertEqual(first, second)
        self.assertIn(first.cancelled_by, (self.actor.user_id, self.worker.user_id))

    def test_cancel_racing_claim_and_completion_keeps_consistent_terminal_state(self):
        for operation in ("claim", "complete"):
            job = self.store.create(self.worker, self.a, operation, self.payload)
            token = self.store.claim(self.worker, self.a, job) if operation == "complete" else None
            start = Barrier(2)
            def cancel():
                with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                    start.wait(timeout=5)
                    try:
                        PostgresJobStore(connection).cancel(self.actor, self.a, job)
                        return True
                    except ValueError:
                        return False
            def work():
                with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                    store = PostgresJobStore(connection)
                    start.wait(timeout=5)
                    try:
                        if operation == "claim":
                            store.claim(self.worker, self.a, job)
                        else:
                            store.checkpoint(self.worker, self.a, job, token, {"step": "prepared"}, complete=True)
                        return True
                    except ValueError:
                        return False
            with ThreadPoolExecutor(max_workers=2) as workers:
                cancelled = workers.submit(cancel)
                worked = workers.submit(work)
                cancellation_won, work_won = cancelled.result(timeout=5), worked.result(timeout=5)
            state = self.store.get(self.actor, self.a, job)
            with self.subTest(operation=operation):
                if operation == "claim":
                    self.assertTrue(cancellation_won)
                    self.assertEqual(state["status"], "cancelled")
                else:
                    self.assertNotEqual(cancellation_won, work_won)
                    self.assertEqual(state["status"], "cancelled" if cancellation_won else "completed")
                self.assertEqual(self.owner.execute("""
                    SELECT lease_token,lease_until FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
                """, (self.a, job)).fetchone(), (None, None))
                with self.assertRaises(ValueError):
                    self.store.claim(self.worker, self.a, job)

    def test_cancel_checks_scope_permissions_and_completed_job_boundary(self):
        job = self.create()
        for actor in (
            Principal("viewer", self.a, "viewer"),
            Principal("api", self.a, "editor", api_scopes=frozenset({"records:read"})),
            Principal("staff", self.a, "editor", staff_role="platform_owner", mfa_verified=True),
            self.other,
        ):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                self.store.cancel(actor, self.a, job)
        with self.assertRaises(ValueError):
            self.store.cancel(self.other, self.b, job)
        with self.assertRaises(ValueError):
            self.store.cancel(self.actor, self.a, uuid4())
        with self.assertRaises(PermissionError):
            PostgresJobStore(self.owner).cancel(self.actor, self.a, job)
        token = self.store.claim(self.worker, self.a, job)
        self.store.checkpoint(self.worker, self.a, job, token, {"step": "prepared"}, complete=True)
        with self.assertRaises(ValueError):
            self.store.cancel(self.actor, self.a, job)
        self.assertEqual(self.store.get(self.actor, self.a, job)["status"], "completed")
        self.assertEqual(self.owner.execute("""
            SELECT cancelled_by,cancelled_at FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        """, (self.a, job)).fetchone(), (None, None))
        api_job = self.store.create(self.worker, self.a, "fictional-api-cancel", {})
        api = Principal("fictional-api-editor", self.a, "editor", api_scopes=frozenset({"records:write"}))
        self.assertEqual(self.store.cancel(api, self.a, api_job).cancelled_by, api.user_id)

    def test_cancellation_state_requires_attribution_and_cleared_lease(self):
        job = self.create()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute("UPDATE omnixat.agent_jobs SET status='cancelled' WHERE tenant_id=%s AND id=%s", (self.a, job))
        self.store.cancel(self.actor, self.a, job)
        for update, value in (("cancelled_by", None), ("cancelled_at", None), ("lease_token", uuid4())):
            with self.subTest(field=update), self.assertRaises(psycopg.errors.CheckViolation):
                self.owner.execute(sql.SQL("UPDATE omnixat.agent_jobs SET {}=%s WHERE tenant_id=%s AND id=%s")
                                   .format(sql.Identifier(update)), (value, self.a, job))
        self.assertEqual(self.store.get(self.actor, self.a, job)["status"], "cancelled")

    def test_cancellation_migration_preserves_existing_job_states_and_progress(self):
        database = "omnixat_upgrade_" + uuid4().hex
        self.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        self.addCleanup(lambda: self.admin.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))))
        with psycopg.connect(self.admin.info.dsn, dbname=database, autocommit=True) as db:
            with TemporaryDirectory() as directory:
                previous = Path(directory)
                for migration in MIGRATIONS.glob("[0-9]*.sql"):
                    if migration.name < "0052":
                        copyfile(migration, previous / migration.name)
                with patch("omnixat_core.postgres.MIGRATIONS", previous):
                    migrate(db)
            db.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional upgrade')", (self.a,))
            for status in ("queued", "running", "completed"):
                db.execute("""INSERT INTO omnixat.agent_jobs
                    (tenant_id,request_key,payload_hash,status,checkpoint,created_by,claimed_by,lease_token,lease_until)
                    VALUES (%s,%s,%s,%s,'{"step":"fictional"}'::jsonb,'fictional',%s,%s,%s)
                """, (self.a, status, bytes(32), status, None if status == "queued" else "fictional",
                      uuid4() if status == "running" else None, "2099-01-01T00:00:00Z" if status == "running" else None))
            before = db.execute("SELECT * FROM omnixat.agent_jobs ORDER BY request_key").fetchall()
            migrate(db)
            after = db.execute("SELECT * FROM omnixat.agent_jobs ORDER BY request_key").fetchall()
            self.assertEqual([row[:-2] for row in after], before)
            self.assertTrue(all(row[-2:] == (None, None) for row in after))
            migrate(db)
            self.assertEqual(db.execute("SELECT * FROM omnixat.agent_jobs ORDER BY request_key").fetchall(), after)

    def test_cancellation_rolls_back_when_transaction_deadline_fails(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        with patch('omnixat_core.postgres.monotonic', side_effect=(0, 11)):
            with self.assertRaises(TimeoutError):
                self.store.cancel(self.actor, self.a, job)
        self.assertEqual(self.owner.execute("""
            SELECT status,lease_token,cancelled_by,cancelled_at FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        """, (self.a, job)).fetchone(), ('running', UUID(token), None, None))
        self.store.checkpoint(self.worker, self.a, job, token, {'step': 'recovered'})
        self.store.cancel(self.actor, self.a, job)
        self.assertEqual(self.store.get(self.actor, self.a, job)['status'], 'cancelled')
