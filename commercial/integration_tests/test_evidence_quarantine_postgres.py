from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

import psycopg
from psycopg import sql

from omnixat_core.access import Principal
from omnixat_core.evidence_intake import stage_evidence
from omnixat_core.evidence_postgres import EvidenceConflict, register_evidence
from omnixat_core.evidence_quarantine_postgres import store_quarantined_evidence
from test_postgres import PostgresFixture


class EvidenceQuarantineTests(PostgresFixture):
    original = b"Fictional heading,Amount\r\nFictional item,12\r\n"
    media_type = "text/csv"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        role = sql.Identifier(cls.role)
        for grants in (
            "SELECT, INSERT ON omnixat.evidence_registrations",
            "INSERT (tenant_id, evidence_id, original_bytes) ON omnixat.evidence_quarantine",
            "SELECT (tenant_id, evidence_id, stored_at) ON omnixat.evidence_quarantine",
        ):
            cls.owner.execute(sql.SQL("GRANT " + grants + " TO {}").format(role))

    def setUp(self):
        super().setUp()
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.evidence = register_evidence(
            self.runtime, self.actor, self.a, self.org,
            content_sha256=sha256(self.original).hexdigest(),
            media_type=self.media_type, byte_size=len(self.original),
        )

    def stage(self, original=None, *, media_type=None):
        return stage_evidence(
            BytesIO(self.original if original is None else original),
            media_type=self.media_type if media_type is None else media_type,
            quarantine_dir=self.directory,
        )

    def store(self, staged, *, connection=None, actor=None, tenant=None, organisation=None):
        return store_quarantined_evidence(
            self.runtime if connection is None else connection,
            self.actor if actor is None else actor,
            self.a if tenant is None else tenant,
            self.org if organisation is None else organisation,
            self.evidence.id, staged,
        )

    def saved_bytes(self):
        return self.owner.execute(
            "SELECT original_bytes FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s",
            (self.a, self.evidence.id),
        ).fetchall()

    def test_persists_original_and_replays_receipt_after_reconnect(self):
        with self.stage() as staged:
            first = self.store(staged)
        with psycopg.connect(self.runtime_dsn, autocommit=True) as fresh, self.stage() as staged:
            self.assertEqual(self.store(staged, connection=fresh), first)
        self.assertEqual(first.evidence_id, self.evidence.id)
        self.assertEqual(self.saved_bytes(), [(self.original,)])

    def test_mismatched_metadata_and_tampered_bytes_are_rejected(self):
        with self.stage(media_type="image/png") as staged, self.assertRaises(EvidenceConflict):
            self.store(staged)
        different = b"x" * len(self.original)
        with self.stage(different) as staged, self.assertRaises(EvidenceConflict):
            self.store(replace(staged, content_sha256=self.evidence.content_sha256))
        self.assertEqual(self.saved_bytes(), [])

    def test_rejects_wrong_tenant_organisation_or_actor_before_consuming_bytes(self):
        denied_actors = [
            Principal("viewer", self.a, "viewer"),
            Principal("agent", self.a, "editor", actor_kind="agent"),
            Principal("staff", self.a, "owner", staff_role="platform_owner"),
            Principal("api", self.a, "editor", api_scopes=frozenset({"records:write"})),
        ]
        with self.stage() as staged:
            for actor in denied_actors:
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    self.store(staged, actor=actor)
            with self.assertRaises(KeyError):
                self.store(staged, actor=self.other, tenant=self.b)
            with self.assertRaises(KeyError):
                self.store(staged, organisation=self.evidence.id)
            self.assertEqual(staged.read_for_scan(), self.original)
        self.assertEqual(self.saved_bytes(), [])

    def test_rls_column_grants_and_fingerprint_constraint(self):
        insert = """INSERT INTO omnixat.evidence_quarantine (tenant_id,evidence_id,original_bytes)
                    VALUES (%s,%s,%s)"""
        with self.runtime.transaction():
            self.runtime.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
            with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.runtime.transaction():
                self.runtime.execute(insert, (self.a, self.evidence.id, b"x" * len(self.original)))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.runtime.transaction():
                self.runtime.execute(insert, (self.b, self.evidence.id, self.original))
        with self.stage() as staged:
            self.store(staged)
        self.assertEqual(self.runtime.execute("SELECT evidence_id FROM omnixat.evidence_quarantine").fetchall(), [])
        for query in (
            "SELECT original_bytes FROM omnixat.evidence_quarantine",
            "UPDATE omnixat.evidence_quarantine SET original_bytes=''::bytea",
            "DELETE FROM omnixat.evidence_quarantine",
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.runtime.execute(query)

    def test_interrupted_read_leaves_no_row_and_retry_succeeds(self):
        with self.stage() as staged:
            staged.read_for_scan(1)
            with self.assertRaises(EvidenceConflict):
                self.store(staged)
        self.assertEqual(self.saved_bytes(), [])
        with self.stage() as staged:
            self.store(staged)
        self.assertEqual(self.saved_bytes(), [(self.original,)])

    def test_concurrent_uploads_commit_one_receipt(self):
        barrier = Barrier(2, timeout=5)

        def attempt():
            with psycopg.connect(self.runtime_dsn, autocommit=True) as fresh, self.stage() as staged:
                barrier.wait()
                return self.store(staged, connection=fresh)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [pool.submit(attempt) for _ in range(2)]
            self.assertEqual(first.result(timeout=10), second.result(timeout=10))
        self.assertEqual(self.saved_bytes(), [(self.original,)])
