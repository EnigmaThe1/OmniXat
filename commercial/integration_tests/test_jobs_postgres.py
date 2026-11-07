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
from omnixat_core.job_tasks import EvidencePreparationTask
from omnixat_core.postgres import CreationConflict, TenantRecords, tenant_records
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
        cls.owner.execute(sql.SQL("GRANT SELECT ON omnixat.tenants,omnixat.organisations TO {}").format(role))
        cls.owner.execute(sql.SQL(
            "GRANT SELECT,INSERT ON omnixat.notes,omnixat.record_creations,omnixat.agent_job_note_effects,omnixat.agent_job_failures TO {}"
        ).format(role))
        cls.owner.execute(sql.SQL("GRANT SELECT ON omnixat.evidence_registrations TO {}").format(role))
        cls.owner.execute(sql.SQL("GRANT SELECT,INSERT ON omnixat.agent_job_evidence_tasks TO {}").format(role))
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
            self.assertEqual(db.execute("SELECT count(*) FROM omnixat.agent_job_evidence_tasks").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT count(*) FROM omnixat.agent_job_csv_plans").fetchone(), (0,))
            self.assertEqual(db.execute('SELECT count(*) FROM omnixat.agent_job_csv_effects').fetchone(), (0,))
            self.assertIsNotNone(db.execute("SELECT to_regprocedure('omnixat_extraction.read_job_csv_summary(uuid,text,uuid,bytea)')").fetchone()[0])
            previous_columns = len(before[0])
            self.assertEqual([row[:previous_columns] for row in after], before)
            self.assertTrue(all(row[previous_columns:previous_columns + 2] == (None, None) for row in after))
            self.assertEqual(db.execute("SELECT attempt_limit,attempts_started FROM omnixat.agent_jobs").fetchall(), [(3, 0)] * 3)
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


    def test_job_note_effect_replays_after_reconnect_and_worker_recovery(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        receipt = self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional note")
        self.assertEqual((receipt.job_id, receipt.organisation_id, receipt.created_by),
                         (job, self.org, self.worker.user_id))
        with psycopg.connect(self.job_dsn, autocommit=True) as connection:
            self.assertEqual(PostgresJobStore(connection).create_note_effect(
                self.worker, self.a, job, token, "note-1", self.org, "Fictional note"), receipt)
        self.expire(job)
        replacement = Principal("fictional-recovered-agent", self.a, "editor", actor_kind="agent")
        new = self.store.claim(replacement, self.a, job)
        with self.assertRaises(ValueError):
            self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional note")
        self.assertEqual(self.store.create_note_effect(replacement, self.a, job, new, "note-1", self.org, "Fictional note"), receipt)
        with tenant_records(self.job_connection, replacement, self.a) as records:
            self.assertEqual(records.get_note(receipt.note_id), {
                "id": receipt.note_id, "organisation_id": self.org, "body": "Fictional note", "created_by": self.worker.user_id,
            })
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchone(), (1,))
        self.assertEqual(self.store.get(replacement, self.a, job)["checkpoint"], {})
        self.assertEqual(self.job_connection.execute("SELECT * FROM omnixat.agent_job_note_effects").fetchall(), [])

    def test_concurrent_job_note_effects_return_one_note_and_receipt(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        start = Barrier(2)
        def create_note():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                return PostgresJobStore(connection).create_note_effect(
                    self.worker, self.a, job, token, "note-1", self.org, "Fictional concurrent note")
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: create_note(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.owner.execute("SELECT note_id FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchall(), [(first.note_id,)])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.record_creations WHERE tenant_id=%s AND note_id=%s",
                                           (self.a, first.note_id)).fetchone(), (1,))

    def test_job_note_effect_conflicts_and_invalid_parents_leave_no_extra_records(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        receipt = self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional note")
        with tenant_records(self.runtime, self.other, self.b, write=True) as records:
            foreign_org = records.create_organisation("Fictional foreign organisation")["id"]
        for org, body in ((self.org, "Different note"), (foreign_org, "Fictional note")):
            with self.subTest(org=org), self.assertRaises(CreationConflict):
                self.store.create_note_effect(self.worker, self.a, job, token, "note-1", org, body)
        for org in (uuid4(), foreign_org):
            with self.subTest(org=org), self.assertRaises(KeyError):
                self.store.create_note_effect(self.worker, self.a, job, token, "missing-parent", org, "Fictional note")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.store.create_note_effect(self.worker, self.a, job, token, "empty-note", self.org, " ")
        self.owner.execute("UPDATE omnixat.notes SET body='Fictional changed note' WHERE tenant_id=%s AND id=%s",
                           (self.a, receipt.note_id))
        with self.assertRaises(CreationConflict):
            self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional note")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchone(), (1,))
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.record_creations WHERE tenant_id=%s AND operation='note.create'",
                                           (self.a,)).fetchone(), (2,))

    def test_job_note_effect_checks_scope_authority_and_terminal_states(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        for actor in (
            Principal("viewer", self.a, "viewer"),
            Principal("api", self.a, "editor", api_scopes=frozenset({"records:write"})),
            Principal("staff", self.a, "editor", staff_role="platform_owner", mfa_verified=True), self.other,
        ):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                self.store.create_note_effect(actor, self.a, job, token, "forbidden", self.org, "Fictional note")
        for tenant, actor, chosen_job, chosen_token in (
            (self.b, self.other, job, token), (self.a, self.worker, uuid4(), token),
            (self.a, self.worker, job, uuid4()), (self.a, self.actor, job, token),
        ):
            with self.subTest(tenant=tenant, actor=actor.user_id), self.assertRaises(ValueError):
                self.store.create_note_effect(actor, tenant, chosen_job, chosen_token, "forbidden", self.org, "Fictional note")
        for key in (None, "", "bad key", "x" * 129):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.create_note_effect(self.worker, self.a, job, token, key, self.org, "Fictional note")
        self.store.cancel(self.actor, self.a, job)
        with self.assertRaises(ValueError):
            self.store.create_note_effect(self.worker, self.a, job, token, "cancelled", self.org, "Fictional note")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchone(), (0,))

    def test_job_note_effect_deadline_failure_rolls_back_note_audit_and_receipt(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        before = self.owner.execute("SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s", (self.a,)).fetchone()
        with patch('omnixat_core.postgres.monotonic', side_effect=(0, 11)):
            with self.assertRaises(TimeoutError):
                self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional rollback note")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s", (self.a,)).fetchone(), before)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchone(), (0,))
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.record_creations WHERE tenant_id=%s AND operation='note.create'",
                                           (self.a,)).fetchone(), (1,))
        self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional rollback note")

    def test_job_note_effect_rechecks_lease_after_note_creation(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()+interval '1 second' WHERE tenant_id=%s AND id=%s",
                           (self.a, job))
        original_create = TenantRecords.create_note
        created = []
        def slow_note(records, organisation, body):
            created.append(original_create(records, organisation, body))
            records._connection.execute("SELECT pg_sleep(1.1)")
            return created[-1]
        with patch('omnixat_core.jobs_postgres.TenantRecords.create_note', autospec=True, side_effect=slow_note):
            with self.assertRaises(ValueError):
                self.store.create_note_effect(self.worker, self.a, job, token, "note-1", self.org, "Fictional slow note")
        self.assertEqual(len(created), 1)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s AND id=%s",
                                           (self.a, created[0]["id"])).fetchone(), (0,))
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchone(), (0,))

    def test_job_note_effect_and_cancellation_serialize(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        start = Barrier(2)
        def effect():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                try:
                    return PostgresJobStore(connection).create_note_effect(
                        self.worker, self.a, job, token, "note-1", self.org, "Fictional racing note")
                except ValueError:
                    return None
        def cancel():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                return PostgresJobStore(connection).cancel(self.actor, self.a, job)
        with ThreadPoolExecutor(max_workers=2) as workers:
            note_result = workers.submit(effect)
            cancel_result = workers.submit(cancel)
            receipt = note_result.result(timeout=5)
            cancel_result.result(timeout=5)
        self.assertEqual(self.store.get(self.actor, self.a, job)["status"], "cancelled")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_note_effects WHERE tenant_id=%s", (self.a,)).fetchone(),
                         (0 if receipt is None else 1,))
        with self.assertRaises(ValueError):
            self.store.create_note_effect(self.worker, self.a, job, token, "note-2", self.org, "Fictional later note")


    def test_retry_budget_delay_and_terminal_failure_are_persisted(self):
        job = self.store.create(self.worker, self.a, "retry-budget", self.payload, max_attempts=2)
        self.assertEqual(self.store.create(self.worker, self.a, "retry-budget", self.payload, max_attempts=2), job)
        with self.assertRaises(ValueError):
            self.store.create(self.worker, self.a, "retry-budget", self.payload, max_attempts=3)
        token = self.store.claim(self.worker, self.a, job)
        first = self.store.fail(self.worker, self.a, job, token, "temporary_dependency", retryable=True)
        self.assertTrue(first.will_retry)
        self.assertIsNotNone(first.retry_at)
        self.assertEqual(self.store.get(self.worker, self.a, job)["status"], "queued")
        with self.assertRaises(ValueError):
            self.store.claim(self.worker, self.a, job)
        with self.assertRaises(ValueError):
            self.store.checkpoint(self.worker, self.a, job, token, {"step": "stale"})
        state = self.store.retry_state(self.worker, self.a, job)
        self.assertEqual((state.attempt_limit, state.attempts_started, state.retry_at, state.failure_code),
                         (2, 1, first.retry_at, "temporary_dependency"))
        self.owner.execute("UPDATE omnixat.agent_jobs SET retry_at=clock_timestamp()-interval '1 second' WHERE tenant_id=%s AND id=%s",
                           (self.a, job))
        token = self.store.claim(self.worker, self.a, job)
        last = self.store.fail(self.worker, self.a, job, token, "temporary_dependency", retryable=True)
        self.assertFalse(last.will_retry)
        self.assertIsNone(last.retry_at)
        self.assertEqual(self.store.get(self.worker, self.a, job)["status"], "failed")
        state = self.store.retry_state(self.worker, self.a, job)
        self.assertEqual(state.attempts_started, 2)
        self.assertIsNotNone(state.failed_at)
        for action in (lambda: self.store.claim(self.worker, self.a, job), lambda: self.store.cancel(self.actor, self.a, job)):
            with self.assertRaises(ValueError):
                action()

    def test_expired_final_claim_persists_exhaustion_when_claim_is_rejected(self):
        job = self.store.create(self.worker, self.a, "one-attempt", {}, max_attempts=1)
        token = self.store.claim(self.worker, self.a, job)
        self.expire(job)
        with self.assertRaises(ValueError):
            self.store.claim(self.worker, self.a, job)
        self.assertEqual(self.store.get(self.worker, self.a, job)["status"], "failed")
        state = self.store.retry_state(self.worker, self.a, job)
        self.assertEqual((state.attempts_started, state.failure_code), (1, "lease_exhausted"))
        self.assertIsNotNone(state.failed_at)
        self.assertEqual(self.owner.execute("SELECT lease_token,lease_until FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s",
                                           (self.a, job)).fetchone(), (None, None))
        with self.assertRaises(ValueError):
            self.store.fail(self.worker, self.a, job, token, "unexpected_error", retryable=False)

    def test_failure_receipt_replay_preserves_new_claim_and_rejects_changed_outcomes(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        start = Barrier(2)
        def fail():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                return PostgresJobStore(connection).fail(
                    self.worker, self.a, job, token, "source_unavailable", retryable=True, retry_after_seconds=0)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: fail(), range(2)))
        self.assertEqual(first, second)
        new = self.store.claim(self.worker, self.a, job)
        with psycopg.connect(self.job_dsn, autocommit=True) as connection:
            self.assertEqual(PostgresJobStore(connection).fail(
                self.worker, self.a, job, token, "source_unavailable", retryable=True, retry_after_seconds=0), first)
        for actor, code, retryable, delay in (
            (self.actor, "source_unavailable", True, 0), (self.worker, "unexpected_error", True, 0),
            (self.worker, "source_unavailable", False, 0), (self.worker, "source_unavailable", True, 1),
        ):
            with self.subTest(actor=actor.user_id, code=code), self.assertRaises(ValueError):
                self.store.fail(actor, self.a, job, token, code, retryable=retryable, retry_after_seconds=delay)
        self.assertEqual(self.owner.execute("SELECT lease_token,status FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s",
                                           (self.a, job)).fetchone(), (UUID(new), "running"))
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_failures WHERE tenant_id=%s AND job_id=%s",
                                           (self.a, job)).fetchone(), (1,))
        self.store.checkpoint(self.worker, self.a, job, new, {"step": "recovered"}, complete=True)

    def test_failure_and_retry_state_enforce_permissions_scope_and_validation(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        viewer = Principal("viewer", self.a, "viewer")
        self.assertEqual(self.store.retry_state(viewer, self.a, job).attempts_started, 1)
        for actor in (viewer, Principal("api", self.a, "editor", api_scopes=frozenset({"records:read"})),
                      Principal("staff", self.a, "editor", staff_role="platform_owner", mfa_verified=True)):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                self.store.fail(actor, self.a, job, token, "unexpected_error", retryable=False)
        with self.assertRaises(ValueError):
            self.store.fail(self.other, self.b, job, token, "unexpected_error", retryable=False)
        with self.assertRaises(KeyError):
            self.store.retry_state(self.other, self.b, job)
        for code, retryable, delay in (("private exception text", True, 0), ([], True, 0),
                                       ("unexpected_error", 1, 0), ("unexpected_error", True, -1),
                                       ("unexpected_error", True, 86401), ("unexpected_error", True, True)):
            with self.subTest(code=code, delay=delay), self.assertRaises(ValueError):
                self.store.fail(self.worker, self.a, job, token, code, retryable=retryable, retry_after_seconds=delay)
        for limit in (0, 21, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.store.create(self.worker, self.a, "invalid-budget", {}, max_attempts=limit)
        self.assertEqual(self.job_connection.execute("SELECT * FROM omnixat.agent_job_failures").fetchall(), [])
        self.assertEqual(self.store.get(self.worker, self.a, job)["status"], "running")

    def test_failure_rolls_back_receipt_and_state_on_commit_deadline(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        with patch('omnixat_core.postgres.monotonic', side_effect=(0, 11)):
            with self.assertRaises(TimeoutError):
                self.store.fail(self.worker, self.a, job, token, "invalid_input", retryable=False)
        self.assertEqual(self.owner.execute("SELECT status,lease_token,failure_code,failed_at FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s",
                                           (self.a, job)).fetchone(), ("running", UUID(token), None, None))
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.agent_job_failures WHERE tenant_id=%s AND job_id=%s",
                                           (self.a, job)).fetchone(), (0,))
        self.assertFalse(self.store.fail(self.worker, self.a, job, token, "invalid_input", retryable=False).will_retry)

    def test_failure_races_terminal_transitions_without_overwriting_winner(self):
        for operation in ("cancel", "complete"):
            job = self.store.create(self.worker, self.a, "failure-race-" + operation, {})
            token = self.store.claim(self.worker, self.a, job)
            start = Barrier(2)
            def fail():
                with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                    start.wait(timeout=5)
                    try:
                        PostgresJobStore(connection).fail(self.worker, self.a, job, token, "unexpected_error", retryable=False)
                        return True
                    except ValueError:
                        return False
            def finish():
                with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                    store = PostgresJobStore(connection)
                    start.wait(timeout=5)
                    try:
                        if operation == "cancel":
                            store.cancel(self.actor, self.a, job)
                        else:
                            store.checkpoint(self.worker, self.a, job, token, {}, complete=True)
                        return True
                    except ValueError:
                        return False
            with ThreadPoolExecutor(max_workers=2) as workers:
                failed = workers.submit(fail)
                finished = workers.submit(finish)
                failure_won, other_won = failed.result(timeout=5), finished.result(timeout=5)
            self.assertNotEqual(failure_won, other_won)
            self.assertEqual(self.store.get(self.actor, self.a, job)["status"],
                             "failed" if failure_won else ("cancelled" if operation == "cancel" else "completed"))

    def test_delayed_retry_cancellation_preserves_budget_and_failure_history(self):
        job = self.create()
        token = self.store.claim(self.worker, self.a, job)
        receipt = self.store.fail(self.worker, self.a, job, token, 'temporary_dependency', retryable=True)
        self.store.cancel(self.actor, self.a, job)
        self.assertEqual(self.store.get(self.actor, self.a, job)['status'], 'cancelled')
        state = self.store.retry_state(self.actor, self.a, job)
        self.assertEqual((state.attempts_started, state.failure_code, state.retry_at), (1, 'temporary_dependency', None))
        self.assertEqual(self.store.fail(self.worker, self.a, job, token, 'temporary_dependency', retryable=True), receipt)
        with self.assertRaises(ValueError):
            self.store.claim(self.worker, self.a, job)

    def evidence_task(self):
        evidence, digest = uuid4(), b'a' * 32
        self.owner.execute("""INSERT INTO omnixat.evidence_registrations
            (tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by)
            VALUES (%s,%s,%s,%s,'text/csv',12,'fictional-register')
        """, (self.a, evidence, self.org, digest))
        return EvidencePreparationTask(self.org, evidence, digest)

    def test_evidence_task_recovers_exact_inputs_after_restart_and_reclaim(self):
        task = self.evidence_task()
        job = self.store.create_evidence_task(self.worker, self.a, 'task', task)
        token = self.store.claim(self.worker, self.a, job)
        self.store.checkpoint(self.worker, self.a, job, token, {'step': 'registered'})
        self.expire(job)
        with psycopg.connect(self.job_dsn, autocommit=True) as connection:
            recovered = PostgresJobStore(connection)
            self.assertNotEqual(token, recovered.claim(self.actor, self.a, job))
            self.assertEqual(recovered.get_evidence_task(self.actor, self.a, job), task)
            self.assertEqual(recovered.get(self.actor, self.a, job)['checkpoint'], {'step': 'registered'})
            self.assertEqual(recovered.create_evidence_task(self.actor, self.a, 'task', task), job)
        self.assertEqual(self.owner.execute('SELECT created_by FROM omnixat.agent_jobs WHERE id=%s', (job,)).fetchone(),
                         (self.worker.user_id,))
        self.store.cancel(self.actor, self.a, job)
        self.assertEqual(self.store.get_evidence_task(self.actor, self.a, job), task)

    def test_evidence_task_concurrent_replay_and_changed_limit_conflict(self):
        task = self.evidence_task()
        start = Barrier(2)
        def create():
            with psycopg.connect(self.job_dsn, autocommit=True) as connection:
                start.wait(timeout=5)
                return PostgresJobStore(connection).create_evidence_task(self.worker, self.a, 'task-race', task)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: create(), range(2)))
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, 'Idempotency key reused'):
            self.store.create_evidence_task(self.worker, self.a, 'task-race', task, max_attempts=4)
        # Same tenant, different valid evidence under the same creation key conflicts.
        self.owner.execute("""INSERT INTO omnixat.evidence_registrations
            (tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by)
            VALUES (%s,%s,%s,%s,'text/csv',12,'fictional-register')
        """, (self.a, uuid4(), self.org, b'b'*32))
        evidence = self.owner.execute('SELECT id FROM omnixat.evidence_registrations WHERE tenant_id=%s AND content_sha256=%s',
                                      (self.a, b'b'*32)).fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'Idempotency key reused'):
            self.store.create_evidence_task(self.worker, self.a, 'task-race', EvidencePreparationTask(self.org, evidence, b'b'*32))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_evidence_tasks WHERE tenant_id=%s',
                                           (self.a,)).fetchone(), (1,))

    def test_evidence_task_rejects_wrong_scope_parent_and_fingerprint(self):
        task = self.evidence_task()
        for invalid in [EvidencePreparationTask(uuid4(), task.evidence_id, task.content_sha256),
                        EvidencePreparationTask(task.organisation_id, uuid4(), task.content_sha256),
                        EvidencePreparationTask(task.organisation_id, task.evidence_id, b'x'*32)]:
            with self.assertRaises(KeyError):
                self.store.create_evidence_task(self.worker, self.a, 'bad', invalid)
        with self.assertRaises(KeyError):
            self.store.create_evidence_task(self.other, self.b, 'foreign', task)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_jobs WHERE tenant_id IN (%s,%s)',
                                           (self.a, self.b)).fetchone(), (0,))

    def test_evidence_task_permissions_and_hash_only_legacy_jobs(self):
        task = self.evidence_task()
        job = self.store.create_evidence_task(self.worker, self.a, 'access', task)
        viewer = Principal('viewer', self.a, 'viewer')
        self.assertEqual(self.store.get_evidence_task(viewer, self.a, job), task)
        for actor in [viewer, self.other,
                      Principal('api', self.a, 'editor', api_scopes=frozenset({'records:write'})),
                      Principal('staff', None, staff_role='platform_owner', mfa_verified=True)]:
            with self.assertRaises(PermissionError):
                self.store.create_evidence_task(actor, self.a, 'denied', task)
        with self.assertRaises(KeyError):
            self.store.get_evidence_task(self.other, self.b, job)
        with self.assertRaises(PermissionError):
            self.store.get_evidence_task(self.other, self.a, job)
        legacy = self.store.create(self.worker, self.a, 'legacy', task.payload())
        with self.assertRaises(KeyError):
            self.store.get_evidence_task(self.worker, self.a, legacy)
        with self.assertRaisesRegex(ValueError, 'Saved task specification unavailable'):
            self.store.create_evidence_task(self.worker, self.a, 'legacy', task)
        self.assertEqual(self.store.get(self.worker, self.a, legacy)['status'], 'queued')

    def test_evidence_task_and_job_roll_back_together(self):
        task = self.evidence_task()
        original = self.store._insert_job
        def interrupt(*args):
            original(*args)
            raise RuntimeError('fictional interruption')
        with patch.object(self.store, '_insert_job', side_effect=interrupt), self.assertRaises(RuntimeError):
            self.store.create_evidence_task(self.worker, self.a, 'rollback', task)
        # Also fail after both inserts, at the transaction's final deadline check.
        from omnixat_core import postgres
        with patch.object(postgres, 'monotonic', side_effect=[0, 11]), self.assertRaises(TimeoutError):
            self.store.create_evidence_task(self.worker, self.a, 'rollback', task)
        for table in ['agent_jobs', 'agent_job_evidence_tasks']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.' + table + ' WHERE tenant_id=%s',
                                               (self.a,)).fetchone(), (0,))
        self.store.create_evidence_task(self.worker, self.a, 'rollback', task)

    def test_evidence_task_database_constraints_and_runtime_immutability(self):
        task = self.evidence_task()
        job = self.store.create_evidence_task(self.worker, self.a, 'constraints', task)
        self.assertEqual(self.job_connection.execute('SELECT count(*) FROM omnixat.agent_job_evidence_tasks').fetchone(), (0,))
        for statement in ['UPDATE omnixat.agent_job_evidence_tasks SET version=1', 'DELETE FROM omnixat.agent_job_evidence_tasks']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.job_connection.execute(statement)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute('UPDATE omnixat.agent_job_evidence_tasks SET version=2 WHERE job_id=%s', (job,))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_evidence_tasks SET content_sha256=%s WHERE job_id=%s', (b'z'*32, job))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_evidence_tasks SET tenant_id=%s WHERE job_id=%s', (self.b, job))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_evidence_tasks SET organisation_id=%s WHERE job_id=%s', (uuid4(), job))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_evidence_tasks SET job_id=%s WHERE job_id=%s', (uuid4(), job))

    def test_evidence_task_validation_rejects_arbitrary_inputs(self):
        for organisation, evidence, digest in [('bad', uuid4(), b'x'*32), (uuid4(), 'bad', b'x'*32),
                                                (uuid4(), uuid4(), b'short'), (uuid4(), uuid4(), 'a'*64)]:
            with self.assertRaises(ValueError):
                EvidencePreparationTask(organisation, evidence, digest)
        with self.assertRaises(ValueError):
            self.store.create_evidence_task(self.worker, self.a, 'bad', {'body': 'not task data'})
        task = self.evidence_task()
        for key, limit in [('', 3), ('valid', True), ('valid', 21)]:
            with self.assertRaises(ValueError):
                self.store.create_evidence_task(self.worker, self.a, key, task, max_attempts=limit)
