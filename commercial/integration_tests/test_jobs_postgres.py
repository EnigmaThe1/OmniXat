"""PostgreSQL job contract with fictional reference-only payloads and checkpoints."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import Principal
from omnixat_core.jobs_postgres import PostgresJobStore
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
