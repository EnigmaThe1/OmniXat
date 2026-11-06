from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from omnixat_core.access import Principal
from omnixat_core.evidence_csv import AmountCell
from omnixat_core.evidence_extraction_postgres import (
    CSVExtractionConflict, EvidenceNotEligible, _store_csv_extraction,
    extract_and_store_csv_amounts, extract_csv_amounts, read_evidence_for_extraction,
)
from omnixat_core.evidence_intake import stage_evidence
from omnixat_core.evidence_postgres import register_evidence
from omnixat_core.evidence_quarantine_postgres import store_quarantined_evidence
from omnixat_core.evidence_review_postgres import read_csv_extraction_review
from omnixat_core.evidence_scan_postgres import (
    EvidenceScanBusy, EvidenceScanError, scan_quarantined_evidence,
)
from test_postgres import PostgresFixture


class EvidenceScanTests(PostgresFixture):
    original = b"Fictional heading,Amount\r\nFictional row,12\r\nOther row,0.00,,1e2\r\n"
    media_type = "text/csv"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scanner_role = cls.role + "_scanner"
        scanner = sql.Identifier(cls.scanner_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(scanner, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, cls.scanner_role)
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

        gate_role = cls.role + "_gate"
        gate = sql.Identifier(gate_role)
        gate_password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(gate, sql.Literal(gate_password)))
        cls.addClassCleanup(cls.drop_role, gate_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(gate))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_eligible_original(uuid,uuid) TO {}"
        ).format(gate))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb) TO {}"
        ).format(gate))
        cls.gate_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                     user=gate_role, password=gate_password)

        review_role = cls.role + "_review"
        review = sql.Identifier(review_role)
        review_password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(review, sql.Literal(review_password)))
        cls.addClassCleanup(cls.drop_role, review_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(review))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_csv_review(uuid,uuid,uuid) TO {}"
        ).format(review))
        cls.review_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                       user=review_role, password=review_password)

    @classmethod
    def drop_role(cls, role):
        with psycopg.connect(cls.admin.info.dsn, dbname=cls.database, autocommit=True) as db:
            db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        cls.admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))

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

    def gate_connection(self):
        db = psycopg.connect(self.gate_dsn, autocommit=True)
        self.addCleanup(db.close)
        return db

    def set_active_policy(self, version):
        self.owner.execute("""
            INSERT INTO omnixat_extraction.active_scan_policy (policy_version) VALUES (%s)
            ON CONFLICT (singleton) DO UPDATE SET policy_version=EXCLUDED.policy_version
        """, (version,))

    def gate_read(self, db, *, tenant=None, organisation=None):
        return read_evidence_for_extraction(
            db, tenant or self.a, organisation or self.org, self.registration.id,
        )

    def test_extraction_requires_active_policy_and_clean_exact_original(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        with self.assertRaises(EvidenceNotEligible):
            self.gate_read(gate)
        self.run_scan(lambda *_: "clean")
        with self.assertRaises(EvidenceNotEligible):
            self.gate_read(gate)
        self.set_active_policy("fictional-v1")
        admitted = self.gate_read(gate)
        self.assertEqual((admitted.evidence_id, admitted.media_type, admitted.policy_version),
                         (self.registration.id, self.media_type, "fictional-v1"))
        self.assertEqual(admitted.original_bytes, self.original)
        self.assertEqual(admitted.content_sha256, sha256(self.original).hexdigest())
        self.assertNotIn("Fictional heading", repr(admitted))
        self.set_active_policy("fictional-v2")
        with self.assertRaises(EvidenceNotEligible):
            self.gate_read(gate)
        self.run_scan(lambda *_: "blocked", policy="fictional-v2")
        with self.assertRaises(EvidenceNotEligible):
            self.gate_read(gate)

    def test_extraction_denies_live_claim_and_legacy_blocked_verdict(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        self.owner.execute("""
            INSERT INTO omnixat.evidence_scan_claims
                (tenant_id,evidence_id,policy_version,lease_token,expires_at)
            VALUES (%s,%s,'fictional-v1',%s,clock_timestamp() + interval '120 seconds')
        """, (self.a, self.registration.id, uuid4()))
        with self.assertRaises(EvidenceNotEligible):
            self.gate_read(gate)
        self.expire_claim()
        self.assertEqual(self.gate_read(gate).original_bytes, self.original)
        self.owner.execute("""
            INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
            SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
            FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s
        """, (self.a, self.registration.id))
        with self.assertRaises(EvidenceNotEligible):
            self.gate_read(gate)

    def test_extraction_scope_and_execute_only_grants(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        for scope in ({"tenant": self.b}, {"organisation": uuid4()}):
            with self.subTest(scope=scope), self.assertRaises(EvidenceNotEligible):
                self.gate_read(gate, **scope)
        function = "SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)"
        self.assertEqual(gate.execute(function, (self.org, self.registration.id)).fetchall(), [])
        for query, connection in (
            ("SELECT original_bytes FROM omnixat.evidence_quarantine", gate),
            ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v3'", gate),
            (function, self.runtime),
        ):
            params = (self.org, self.registration.id) if query == function else ()
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(query, params)
        with self.assertRaises(PermissionError):
            self.gate_read(self.scanner)

    def test_csv_worker_requires_admission_and_returns_bound_source(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        selection = (AmountCell("amount", 2, 2), AmountCell("vat", 2, 3))
        args = (gate, self.a, self.org, self.registration.id, selection)
        with self.assertRaises(EvidenceNotEligible):
            extract_csv_amounts(*args)
        self.run_scan(lambda *_: "clean")
        extracted = extract_csv_amounts(*args)
        self.assertEqual(extracted.evidence_id, self.registration.id)
        self.assertEqual(extracted.policy_version, "fictional-v1")
        self.assertEqual(extracted.content_sha256, sha256(self.original).hexdigest())
        self.assertEqual(extracted.amounts[0].cell, selection[0])
        self.assertEqual(extracted.amounts[0].amount, Decimal("12"))
        self.assertEqual(extracted.amounts[1].status, "missing")
        self.set_active_policy("fictional-v2")
        with self.assertRaises(EvidenceNotEligible):
            extract_csv_amounts(*args)

    def test_csv_storage_replays_and_rejects_changed_plan(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        job = uuid4()
        args = (gate, self.a, self.org, self.registration.id, job)
        selections = (AmountCell("net", 2, 2), AmountCell("vat", 2, 3))
        receipt = extract_and_store_csv_amounts(*args, selections)
        self.assertEqual(extract_and_store_csv_amounts(*args, selections), receipt)
        with self.assertRaises(CSVExtractionConflict):
            extract_and_store_csv_amounts(*args, (AmountCell("net", 2, 1),))
        row = self.owner.execute("""
            SELECT evidence_id, policy_version, content_sha256, amounts
            FROM omnixat.csv_extraction_results WHERE tenant_id=%s AND job_id=%s
        """, (self.a, job)).fetchone()
        self.assertEqual(row[:3], (self.registration.id, "fictional-v1", sha256(self.original).digest()))
        self.assertEqual(row[3], [
            {"field_name": "net", "row": 2, "column": 2, "status": "found", "amount": "12"},
            {"field_name": "vat", "row": 2, "column": 3, "status": "missing", "amount": None},
        ])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            gate.execute("SELECT * FROM omnixat.csv_extraction_results")

    def test_csv_storage_rechecks_scope_and_policy_after_read(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        result = extract_csv_amounts(
            gate, self.a, self.org, self.registration.id, (AmountCell("net", 2, 2),),
        )
        job = uuid4()
        with self.assertRaises(EvidenceNotEligible):
            _store_csv_extraction(gate, self.b, self.org, job, result)
        self.set_active_policy("fictional-v2")
        with self.assertRaises(EvidenceNotEligible):
            _store_csv_extraction(gate, self.a, self.org, job, result)
        self.assertEqual(self.owner.execute(
            "SELECT count(*) FROM omnixat.csv_extraction_results WHERE job_id=%s", (job,),
        ).fetchone()[0], 0)

    def test_concurrent_csv_storage_replays_one_receipt(self):
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        job = uuid4()
        barrier = Barrier(2, timeout=5)

        def attempt():
            with psycopg.connect(self.gate_dsn, autocommit=True) as gate:
                result = extract_csv_amounts(
                    gate, self.a, self.org, self.registration.id, (AmountCell("net", 2, 2),),
                )
                barrier.wait()
                return _store_csv_extraction(gate, self.a, self.org, job, result)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = (pool.submit(attempt) for _ in range(2))
            self.assertEqual(first.result(timeout=10), second.result(timeout=10))
        self.assertEqual(self.owner.execute(
            "SELECT count(*) FROM omnixat.csv_extraction_results WHERE job_id=%s", (job,),
        ).fetchone()[0], 1)

    def test_csv_write_serializes_with_active_policy_rotation(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        job = uuid4()
        with gate.transaction():
            gate.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
            receipt = gate.execute("""
                SELECT outcome FROM omnixat_extraction.store_csv_result(%s,%s,%s,%s,%s,%s)
            """, (self.org, self.registration.id, job, "fictional-v1", sha256(self.original).digest(),
                  Jsonb([{"field_name": "net", "row": 2, "column": 2, "status": "found", "amount": "12"}])))
            self.assertEqual(receipt.fetchone(), ("stored",))
            with self.assertRaises(psycopg.errors.LockNotAvailable), self.owner.transaction():
                self.owner.execute("SET LOCAL lock_timeout = '100ms'")
                self.set_active_policy("fictional-v2")
        self.set_active_policy("fictional-v2")
        self.assertEqual(self.owner.execute("""
            SELECT policy_version FROM omnixat.csv_extraction_results WHERE tenant_id=%s AND job_id=%s
        """, (self.a, job)).fetchone(), ("fictional-v1",))

    def prepare_csv_review(self):
        gate = self.gate_connection()
        self.addCleanup(self.owner.execute, "DELETE FROM omnixat_extraction.active_scan_policy")
        self.set_active_policy("fictional-v1")
        self.run_scan(lambda *_: "clean")
        selections = (
            AmountCell("total", 3, 2), AmountCell("vat", 3, 3),
            AmountCell("net", 3, 4), AmountCell("fee", 3, 5),
        )
        job = uuid4()
        extract_and_store_csv_amounts(gate, self.a, self.org, self.registration.id, job, selections)
        review = psycopg.connect(self.review_dsn, autocommit=True)
        self.addCleanup(review.close)
        return gate, review, job, selections

    def test_csv_review_returns_candidates_and_only_unresolved_questions(self):
        _, review, job, selections = self.prepare_csv_review()
        actor = Principal("fictional-viewer", self.a, "viewer")
        result = read_csv_extraction_review(review, actor, self.a, self.org, self.registration.id, job)
        self.assertEqual(result.job_id, job)
        self.assertEqual(result.content_sha256, sha256(self.original).hexdigest())
        self.assertEqual(result.amounts[0].amount.as_tuple(), Decimal("0.00").as_tuple())
        self.assertEqual(tuple(prompt.cell for prompt in result.clarifications), selections[1:])
        self.assertEqual([prompt.reason for prompt in result.clarifications], ["blank", "ambiguous", "missing"])
        self.assertTrue(all(prompt.question.endswith("?") for prompt in result.clarifications))
        self.assertNotIn("1e2", repr(result))
        self.set_active_policy("fictional-v2")
        with self.assertRaises(EvidenceNotEligible):
            read_csv_extraction_review(review, actor, self.a, self.org, self.registration.id, job)

    def test_csv_review_denies_wrong_scope_and_separates_database_roles(self):
        gate, review, job, _ = self.prepare_csv_review()
        for actor in (
            Principal("fictional-other", self.b, "owner"),
            Principal("fictional-agent", self.a, "owner", actor_kind="agent"),
            Principal("fictional-api", self.a, "owner", api_scopes=frozenset({"evidence:read"})),
            Principal("fictional-staff", self.a, "owner", staff_role="platform_owner"),
        ):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                read_csv_extraction_review(review, actor, self.a, self.org, self.registration.id, job)
        with self.assertRaises(EvidenceNotEligible):
            read_csv_extraction_review(review, self.other, self.b, self.org, self.registration.id, job)
        with self.assertRaises(EvidenceNotEligible):
            read_csv_extraction_review(review, self.actor, self.a, uuid4(), self.registration.id, job)
        with self.assertRaises(PermissionError):
            read_csv_extraction_review(gate, self.actor, self.a, self.org, self.registration.id, job)
        for query, params in (
            ("SELECT original_bytes FROM omnixat.evidence_quarantine", ()),
            ("SELECT * FROM omnixat.csv_extraction_results", ()),
            ("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)", (self.org, self.registration.id)),
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                review.execute(query, params)

    def test_csv_review_fails_closed_on_invalid_stored_amount(self):
        _, review, job, _ = self.prepare_csv_review()
        self.owner.execute("""
            UPDATE omnixat.csv_extraction_results SET amounts=%s WHERE tenant_id=%s AND job_id=%s
        """, (Jsonb([{"field_name": "total", "row": 3, "column": 2, "status": "found", "amount": "NaN"}]),
              self.a, job))
        with self.assertRaises(EvidenceNotEligible):
            read_csv_extraction_review(review, self.actor, self.a, self.org, self.registration.id, job)
