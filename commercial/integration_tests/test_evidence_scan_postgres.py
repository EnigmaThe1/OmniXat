from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus

from omnixat_core.evidence_intake import stage_evidence
from omnixat_core.evidence_postgres import register_evidence
from omnixat_core.evidence_quarantine_postgres import store_quarantined_evidence
from omnixat_core.evidence_scan_postgres import (
    EvidenceScanBusy, EvidenceScanError, scan_quarantined_evidence,
)
from test_postgres import PostgresFixture


class EvidenceScanTests(PostgresFixture):
    original = b"Fictional heading,Amount\r\nFictional row,12\r\n"
    media_type = "text/csv"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scanner_role = cls.role + "_scanner"
        scanner = sql.Identifier(cls.scanner_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(scanner, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_scanner)
        cls.scanner_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                        user=cls.scanner_role, password=password)
        for grants in (
            "USAGE ON SCHEMA omnixat",
            "SELECT ON omnixat.evidence_registrations, omnixat.evidence_quarantine",
            "SELECT ON omnixat.evidence_scan_verdicts",
            "SELECT, INSERT, DELETE ON omnixat.evidence_scan_claims",
            "UPDATE (lease_token, expires_at) ON omnixat.evidence_scan_claims",
            "INSERT (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict) "
            "ON omnixat.evidence_scan_verdicts",
        ):
            cls.owner.execute(sql.SQL("GRANT " + grants + " TO {}").format(scanner))
        for grants in (
            "SELECT, INSERT ON omnixat.evidence_registrations",
            "INSERT (tenant_id, evidence_id, original_bytes) ON omnixat.evidence_quarantine",
            "SELECT (tenant_id, evidence_id, stored_at) ON omnixat.evidence_quarantine",
        ):
            cls.owner.execute(sql.SQL("GRANT " + grants + " TO {}").format(sql.Identifier(cls.role)))

    @classmethod
    def drop_scanner(cls):
        with psycopg.connect(cls.admin.info.dsn, dbname=cls.database, autocommit=True) as db:
            db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(cls.scanner_role)))
        cls.admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.scanner_role)))

    def scanner_connection(self):
        return psycopg.connect(self.scanner_dsn, autocommit=True)

    def setUp(self):
        super().setUp()
        self.scanner = self.scanner_connection()
        self.addCleanup(self.scanner.close)
        self.registration = register_evidence(
            self.runtime, self.actor, self.a, self.org,
            content_sha256=sha256(self.original).hexdigest(),
            media_type=self.media_type, byte_size=len(self.original),
        )
        with TemporaryDirectory() as directory, stage_evidence(
            BytesIO(self.original), media_type=self.media_type, quarantine_dir=Path(directory),
        ) as staged:
            store_quarantined_evidence(self.runtime, self.actor, self.a, self.org, self.registration.id, staged)

    def run_scan(self, scan, *, policy="fictional-v1", connection=None, tenant=None, org=None, evidence=None):
        return scan_quarantined_evidence(
            self.scanner if connection is None else connection, tenant or self.a, org or self.org,
            evidence or self.registration.id, policy_version=policy, scan=scan,
        )

    def test_receipt_binds_exact_bytes_and_replays_without_rescanning(self):
        def scanner(original, media_type):
            self.assertIs(self.scanner.info.transaction_status, TransactionStatus.IDLE)
            self.assertEqual((original, media_type), (self.original, self.media_type))
            return "clean"

        first = self.run_scan(scanner)
        with self.scanner_connection() as fresh:
            again = self.run_scan(lambda *_: self.fail("Replay called scanner"), connection=fresh)
        self.assertEqual(first, again)
        self.assertEqual(first.verdict, "clean")
        self.assertEqual(self.owner.execute("""
            SELECT content_sha256,byte_size FROM omnixat.evidence_scan_verdicts
            WHERE tenant_id=%s AND evidence_id=%s
        """, (self.a, self.registration.id)).fetchone(), (sha256(self.original).digest(), len(self.original)))
        self.assertEqual(self.run_scan(lambda *_: "blocked", policy="fictional-v2").verdict, "blocked")

    def test_failure_or_unknown_verdict_leaves_no_receipt(self):
        def failed(*_):
            raise OSError("fictional private detail")
        for scanner in (failed, lambda *_: "unknown"):
            with self.assertRaises(EvidenceScanError) as error:
                self.run_scan(scanner)
            self.assertNotIn("fictional private detail", str(error.exception))
        self.assertEqual(self.run_scan(lambda *_: "blocked").verdict, "blocked")

    def test_wrong_scope_and_intake_role_cannot_run_scanner(self):
        for scope in ({"tenant": self.b}, {"org": uuid4()}, {"evidence": uuid4()}):
            with self.subTest(scope=scope), self.assertRaises(KeyError):
                self.run_scan(lambda *_: self.fail("Unscoped scanner called"), **scope)
        with self.assertRaises(PermissionError):
            self.run_scan(lambda *_: self.fail("Intake scanner called"), connection=self.runtime)
        with self.assertRaises(ValueError):
            self.run_scan(lambda *_: self.fail("Invalid policy used"), policy="../untrusted")

    def test_database_enforces_digest_rls_and_role_separation(self):
        with self.scanner.transaction():
            self.scanner.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
            query = """INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                VALUES (%s,%s,%s,%s,'fictional-v1','clean')"""
            with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.scanner.transaction():
                self.scanner.execute(query, (self.a, self.registration.id, bytes(32), len(self.original)))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.scanner.transaction():
                self.scanner.execute(query, (self.b, self.registration.id, bytes(32), len(self.original)))
        for query, connection in (
            ("DELETE FROM omnixat.evidence_quarantine", self.scanner),
            ("UPDATE omnixat.evidence_scan_verdicts SET verdict='clean'", self.scanner),
            ("SELECT * FROM omnixat.evidence_scan_verdicts", self.runtime),
            ("SELECT * FROM omnixat.evidence_scan_claims", self.runtime),
            ("UPDATE omnixat.evidence_scan_claims SET policy_version='changed'", self.scanner),
        ):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(query)

    def test_active_claim_excludes_second_worker_without_holding_transaction(self):
        started, finish = Event(), Event()

        def first_scan(*_):
            started.set()
            if not finish.wait(5):
                raise TimeoutError("test scanner timed out")
            return "blocked"

        with ThreadPoolExecutor(max_workers=1) as pool:
            def attempt():
                with self.scanner_connection() as fresh:
                    return self.run_scan(first_scan, connection=fresh)

            result = pool.submit(attempt)
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaises(EvidenceScanBusy):
                    self.run_scan(lambda *_: self.fail("Duplicate scanner called"))
                self.assertEqual(self.run_scan(lambda *_: "clean", policy="fictional-v2").verdict, "clean")
            finally:
                finish.set()
            self.assertEqual(result.result(timeout=10).verdict, "blocked")
        self.assertEqual(self.run_scan(lambda *_: self.fail("Replay rescanned")).verdict, "blocked")

    def expire_claim(self):
        changed = self.owner.execute("""
            UPDATE omnixat.evidence_scan_claims SET expires_at=clock_timestamp() - interval '1 second'
            WHERE tenant_id=%s AND evidence_id=%s AND policy_version='fictional-v1'
        """, (self.a, self.registration.id)).rowcount
        self.assertEqual(changed, 1)

    def test_expired_worker_cannot_publish_even_without_replacement(self):
        def overdue(*_):
            self.expire_claim()
            return "clean"

        with self.assertRaisesRegex(EvidenceScanError, "expired or was replaced"):
            self.run_scan(overdue)
        self.assertEqual(self.run_scan(lambda *_: "blocked").verdict, "blocked")

    def test_recovered_claim_rejects_the_stale_workers_result(self):
        def stale_worker(*_):
            self.expire_claim()
            with self.scanner_connection() as replacement:
                receipt = self.run_scan(lambda *_: "clean", connection=replacement)
                self.assertEqual(receipt.verdict, "clean")
            return "blocked"

        with self.assertRaisesRegex(EvidenceScanError, "expired or was replaced"):
            self.run_scan(stale_worker)
        self.assertEqual(self.run_scan(lambda *_: self.fail("Replay rescanned")).verdict, "clean")
        rows = self.owner.execute("""
            SELECT verdict FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s
        """, (self.a, self.registration.id)).fetchall()
        self.assertEqual(rows, [("clean",)])

    def test_legacy_disagreement_preserves_blocked_precedence(self):
        self.run_scan(lambda *_: "clean")
        self.owner.execute("""
            INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
            SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
            FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s
        """, (self.a, self.registration.id))
        self.assertEqual(self.run_scan(lambda *_: self.fail("Legacy replay rescanned")).verdict, "blocked")
