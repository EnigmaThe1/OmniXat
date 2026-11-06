from concurrent.futures import ThreadPoolExecutor
from datetime import date
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
from omnixat_core.evidence_drafts_postgres import (
    EvidenceDraftConflict, ExpenseDraftConflict, create_csv_draft_amount, create_csv_expense_draft,
    prepare_csv_expense_draft, read_csv_draft_amount, read_csv_expense_draft,
)
from omnixat_core.evidence_extraction_postgres import (
    CSVExtractionConflict, EvidenceNotEligible, _store_csv_extraction,
    extract_and_store_csv_amounts, extract_csv_amounts, read_evidence_for_extraction,
)
from omnixat_core.expense_context import ExpenseDraftContext
from omnixat_core.evidence_intake import stage_evidence
from omnixat_core.evidence_postgres import register_evidence
from omnixat_core.evidence_quarantine_postgres import store_quarantined_evidence
from omnixat_core.evidence_review_postgres import (
    CSVClarificationConflict, read_csv_extraction_review, store_csv_clarification,
)
from omnixat_core.evidence_scan_postgres import (
    EvidenceScanBusy, EvidenceScanError, scan_quarantined_evidence,
)
from omnixat_core.expense_funding_postgres import (
    ExpenseFundingConflict, read_expense_funding_context, record_expense_funding_context,
)
from omnixat_core.expense_journal_postgres import (
    ExpenseJournalConflict, create_expense_journal_draft, prepare_expense_journal_preview, read_expense_journal_draft,
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
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_csv_review_with_answers(uuid,uuid,uuid) TO {}"
        ).format(review))
        cls.review_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                       user=review_role, password=review_password)

        answer_role = cls.role + "_answer"
        answer = sql.Identifier(answer_role)
        answer_password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(answer, sql.Literal(answer_password)))
        cls.addClassCleanup(cls.drop_role, answer_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(answer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.store_csv_answer(uuid,uuid,uuid,text,integer,integer,text,text) TO {}"
        ).format(answer))
        cls.answer_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                       user=answer_role, password=answer_password)

        draft_role = cls.role + "_draft"
        draft = sql.Identifier(draft_role)
        draft_password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(draft, sql.Literal(draft_password)))
        cls.addClassCleanup(cls.drop_role, draft_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(draft))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.create_csv_draft_amount(uuid,uuid,uuid,text,integer,integer,text) TO {}"
        ).format(draft))
        cls.draft_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                      user=draft_role, password=draft_password)

        draft_reader_role = cls.role + "_draft_reader"
        draft_reader = sql.Identifier(draft_reader_role)
        reader_password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(draft_reader, sql.Literal(reader_password)))
        cls.addClassCleanup(cls.drop_role, draft_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(draft_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_csv_draft_amount(uuid,uuid,uuid,text,integer,integer) TO {}"
        ).format(draft_reader))
        cls.draft_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                             user=draft_reader_role, password=reader_password)

        preview_role = cls.role + "_expense_preview"
        preview = sql.Identifier(preview_role)
        preview_password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(preview, sql.Literal(preview_password)))
        cls.addClassCleanup(cls.drop_role, preview_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(preview))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_csv_expense_preview"
            "(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date) TO {}"
        ).format(preview))
        cls.expense_preview_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=preview_role, password=preview_password)

        expense_writer_role = cls.role + "_expense_writer"
        expense_writer = sql.Identifier(expense_writer_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(expense_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, expense_writer_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(expense_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.create_csv_expense_draft"
            "(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date,text,text) TO {}"
        ).format(expense_writer))
        cls.expense_writer_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=expense_writer_role, password=password)

        expense_reader_role = cls.role + "_expense_reader"
        expense_reader = sql.Identifier(expense_reader_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(expense_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, expense_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(expense_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_csv_expense_draft(uuid,uuid) TO {}"
        ).format(expense_reader))
        cls.expense_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=expense_reader_role, password=password)

        funding_role = cls.role + "_funding"
        funding_writer = sql.Identifier(funding_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(funding_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, funding_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(funding_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.record_expense_funding_context"
            "(uuid,uuid,uuid,uuid,text) TO {}"
        ).format(funding_writer))
        cls.funding_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                       user=funding_role, password=password)

        funding_reader_role = cls.role + "_funding_reader"
        funding_reader = sql.Identifier(funding_reader_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(funding_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, funding_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(funding_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_funding_context(uuid,uuid) TO {}"
        ).format(funding_reader))
        cls.funding_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                              user=funding_reader_role, password=password)

        journal_role = cls.role + "_journal_preview"
        journal_reader = sql.Identifier(journal_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(journal_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, journal_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(journal_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_preview(uuid,uuid,uuid) TO {}"
        ).format(journal_reader))
        cls.journal_preview_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=journal_role, password=password)

        journal_writer_role = cls.role + "_journal_writer"
        journal_writer = sql.Identifier(journal_writer_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(journal_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, journal_writer_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(journal_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.create_expense_journal_draft(uuid,uuid,uuid,text) TO {}"
        ).format(journal_writer))
        cls.journal_writer_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                              user=journal_writer_role, password=password)

        journal_review_role = cls.role + "_journal_review"
        journal_review = sql.Identifier(journal_review_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(journal_review, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, journal_review_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(journal_review))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_draft(uuid,uuid) TO {}"
        ).format(journal_review))
        cls.journal_review_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                              user=journal_review_role, password=password)

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

    def test_csv_clarifications_store_exact_answers_without_modifying_candidates(self):
        _, review, job, selections = self.prepare_csv_review()
        with psycopg.connect(self.answer_dsn, autocommit=True) as answer:
            args = (answer, self.actor, self.a, self.org, self.registration.id, job)
            receipt = store_csv_clarification(*args, selections[1], amount="0.00")
            self.assertEqual(receipt, store_csv_clarification(*args, selections[1], amount="0.00"))
            with self.assertRaises(CSVClarificationConflict):
                store_csv_clarification(*args, selections[1], amount="1.00")
            unavailable = store_csv_clarification(*args, selections[2], amount=None)
            with self.assertRaises(PermissionError):
                read_csv_extraction_review(answer, self.actor, self.a, self.org, self.registration.id, job)
            for cell in (selections[0], AmountCell("vat", 2, 3)):
                with self.assertRaises(EvidenceNotEligible):
                    store_csv_clarification(*args, cell, amount="1")
        rows = self.owner.execute("""
            SELECT field_name, amount, answered_by FROM omnixat.csv_clarification_answers
            WHERE tenant_id=%s AND job_id=%s ORDER BY field_name
        """, (self.a, job)).fetchall()
        self.assertEqual(rows, [("net", None, self.actor.user_id), ("vat", "0.00", self.actor.user_id)])
        before = read_csv_extraction_review(review, self.actor, self.a, self.org, self.registration.id, job)
        self.assertEqual([value.status for value in before.amounts], ["found", "blank", "ambiguous", "missing"])
        zero_answer, unavailable_answer = before.answers
        self.assertEqual((zero_answer.cell, zero_answer.answered_by, zero_answer.answered_at),
                         (selections[1], self.actor.user_id, receipt.answered_at))
        self.assertEqual(zero_answer.amount.as_tuple(), Decimal("0.00").as_tuple())
        self.assertEqual((unavailable_answer.cell, unavailable_answer.amount, unavailable_answer.answered_at),
                         (selections[2], None, unavailable.answered_at))
        self.assertEqual(tuple(prompt.cell for prompt in before.clarifications), (selections[3],))

        self.set_active_policy("fictional-v2")
        with self.assertRaises(EvidenceNotEligible):
            read_csv_extraction_review(review, self.actor, self.a, self.org, self.registration.id, job)

    def test_csv_clarifications_enforce_human_scope_grants_and_current_policy(self):
        gate, review, job, selections = self.prepare_csv_review()
        cell = selections[1]
        with psycopg.connect(self.answer_dsn, autocommit=True) as answer:
            scope = (self.a, self.org, self.registration.id, job, cell)
            for actor in (
                Principal("viewer", self.a, "viewer"),
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("bearer", self.a, "editor", api_scopes=frozenset({"evidence:clarify"})),
                Principal("staff", self.a, "owner", staff_role="platform_owner"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    store_csv_clarification(answer, actor, *scope, amount="1")
            for db in (gate, review):
                with self.assertRaises(PermissionError):
                    store_csv_clarification(db, self.actor, *scope, amount="1")
            with self.assertRaises(ValueError):
                store_csv_clarification(answer, self.actor, *scope, amount="1e2")
            with self.assertRaises(EvidenceNotEligible):
                store_csv_clarification(answer, self.other, self.b, self.org, self.registration.id, job, cell, amount="1")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                answer.execute("SELECT * FROM omnixat.csv_clarification_answers")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                store_csv_clarification(answer, self.actor, *scope, amount="1")
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.csv_clarification_answers WHERE job_id=%s
        """, (job,)).fetchone()[0], 0)

    def test_csv_review_denies_answer_with_mismatched_source_coordinates(self):
        _, review, job, selections = self.prepare_csv_review()
        with psycopg.connect(self.answer_dsn, autocommit=True) as answer:
            store_csv_clarification(
                answer, self.actor, self.a, self.org, self.registration.id, job, selections[1], amount="1",
            )
        self.owner.execute("""
            UPDATE omnixat.csv_clarification_answers SET source_row=2
            WHERE tenant_id=%s AND job_id=%s
        """, (self.a, job))
        with self.assertRaises(EvidenceNotEligible):
            read_csv_extraction_review(review, self.actor, self.a, self.org, self.registration.id, job)

    def test_csv_draft_amount_uses_only_exact_resolved_values(self):
        _, _, job, cells = self.prepare_csv_review()
        scope = (self.a, self.org, self.registration.id, job)
        with psycopg.connect(self.answer_dsn, autocommit=True) as answer:
            store_csv_clarification(answer, self.actor, *scope, cells[1], amount="12.340")
            store_csv_clarification(answer, self.actor, *scope, cells[2], amount=None)
        with psycopg.connect(self.draft_dsn, autocommit=True) as draft:
            for cell, kind in zip(cells[:2], ("extracted", "clarified")):
                receipt = create_csv_draft_amount(draft, self.actor, *scope, cell)
                self.assertEqual(receipt.source_kind, kind)
                self.assertEqual(receipt, create_csv_draft_amount(draft, self.actor, *scope, cell))
            for cell in (*cells[2:], AmountCell("vat", 2, 3)):
                with self.subTest(cell=cell), self.assertRaises(EvidenceNotEligible):
                    create_csv_draft_amount(draft, self.actor, *scope, cell)
            with self.assertRaises(EvidenceDraftConflict):
                create_csv_draft_amount(draft, Principal("other-editor", self.a, "editor"), *scope, cells[1])
        self.assertEqual(self.owner.execute("""
            SELECT field_name, amount, source_kind FROM omnixat.evidence_draft_amounts
            WHERE tenant_id=%s AND job_id=%s ORDER BY field_name
        """, (self.a, job)).fetchall(), [("total", "0.00", "extracted"), ("vat", "12.340", "clarified")])

    def test_csv_draft_amount_rechecks_policy_scope_and_role(self):
        _, review, job, cells = self.prepare_csv_review()
        scope = (self.a, self.org, self.registration.id, job, cells[0])
        with psycopg.connect(self.draft_dsn, autocommit=True) as draft:
            for actor in (Principal("viewer", self.a, "viewer"),
                          Principal("agent", self.a, "editor", actor_kind="agent"),
                          Principal("bearer", self.a, "editor", api_scopes=frozenset({"evidence:read", "records:write"})),
                          Principal("staff", self.a, "owner", staff_role="platform_owner")):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    create_csv_draft_amount(draft, actor, *scope)
            with self.assertRaises(PermissionError):
                create_csv_draft_amount(review, self.actor, *scope)
            with self.assertRaises(EvidenceNotEligible):
                create_csv_draft_amount(draft, self.other, self.b, *scope[1:])
            with self.assertRaises(EvidenceNotEligible):
                create_csv_draft_amount(draft, self.actor, self.a, uuid4(), *scope[2:])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                draft.execute("SELECT * FROM omnixat.evidence_draft_amounts")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                create_csv_draft_amount(draft, self.actor, *scope)
        self.assertEqual(self.owner.execute(
            "SELECT count(*) FROM omnixat.evidence_draft_amounts WHERE job_id=%s", (job,),
        ).fetchone()[0], 0)

    def test_csv_draft_read_preserves_amount_and_provenance_until_policy_changes(self):
        _, _, job, cells = self.prepare_csv_review()
        scope = (self.a, self.org, self.registration.id, job)
        viewer = Principal("viewer", self.a, "viewer")
        with psycopg.connect(self.draft_reader_dsn, autocommit=True) as reader:
            with self.assertRaises(EvidenceNotEligible):
                read_csv_draft_amount(reader, viewer, *scope, cells[0])
            with psycopg.connect(self.draft_dsn, autocommit=True) as writer:
                receipt = create_csv_draft_amount(writer, self.actor, *scope, cells[0])
            result = read_csv_draft_amount(reader, viewer, *scope, cells[0])
            self.assertEqual(result.receipt, receipt)
            self.assertEqual(result.amount.as_tuple(), Decimal("0.00").as_tuple())
            self.assertEqual(result.created_by, self.actor.user_id)
            self.assertEqual(result.content_sha256, sha256(self.original).hexdigest())
            self.assertEqual(result.policy_version, "fictional-v1")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                read_csv_draft_amount(reader, viewer, *scope, cells[0])

    def test_csv_draft_read_requires_exact_scope_and_separate_login(self):
        _, _, job, cells = self.prepare_csv_review()
        scope = (self.a, self.org, self.registration.id, job, cells[0])
        with psycopg.connect(self.draft_dsn, autocommit=True) as writer, \
             psycopg.connect(self.draft_reader_dsn, autocommit=True) as reader:
            create_csv_draft_amount(writer, self.actor, *scope)
            for actor in (Principal("agent", self.a, "editor", actor_kind="agent"),
                          Principal("bearer", self.a, "viewer", api_scopes=frozenset({"evidence:read"})),
                          Principal("staff", self.a, "owner", staff_role="platform_owner")):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    read_csv_draft_amount(reader, actor, *scope)
            with self.assertRaises(EvidenceNotEligible):
                read_csv_draft_amount(reader, self.other, self.b, *scope[1:])
            with self.assertRaises(EvidenceNotEligible):
                read_csv_draft_amount(reader, self.actor, self.a, uuid4(), *scope[2:])
            with self.assertRaises(EvidenceNotEligible):
                read_csv_draft_amount(reader, self.actor, *scope[:-1], AmountCell(cells[0].field_name, 2, 2))
            with self.assertRaises(PermissionError):
                read_csv_draft_amount(writer, self.actor, *scope)
            with self.assertRaises(PermissionError):
                create_csv_draft_amount(reader, self.actor, *scope)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.evidence_draft_amounts")

    def test_csv_expense_preview_uses_eligible_amount_and_explicit_context(self):
        _, _, job, cells = self.prepare_csv_review()
        cell = cells[1]
        scope = (self.a, self.org, self.registration.id, job, cell)
        with psycopg.connect(self.answer_dsn, autocommit=True) as answer:
            store_csv_clarification(answer, self.actor, *scope, amount="12.340")
        with psycopg.connect(self.draft_dsn, autocommit=True) as writer:
            receipt = create_csv_draft_amount(writer, self.actor, *scope)
        account, period = uuid4(), uuid4()
        context = ExpenseDraftContext("GBP", date(2026, 11, 1), account)
        with psycopg.connect(self.expense_preview_dsn, autocommit=True) as reader:
            with self.assertRaisesRegex(ValueError, "unavailable"):
                prepare_csv_expense_draft(reader, self.actor, *scope, context=context, period_id=period)
            self.configure_expense_policy(self.a, self.org, period, account)
            preview = prepare_csv_expense_draft(reader, self.actor, *scope, context=context, period_id=period)
            self.assertEqual((preview.source.receipt, preview.amount_pence, preview.context, preview.period_id),
                             (receipt, 1234, context, period))
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                prepare_csv_expense_draft(reader, self.actor, *scope, context=context, period_id=period)

    def configure_expense_policy(self, tenant, org, period, account, *, opened=True, eligible=True):
        self.owner.execute("""INSERT INTO omnixat.expense_accounting_periods
            (tenant_id, organisation_id, id, starts_on, ends_on, open_for_drafts)
            VALUES (%s,%s,%s,'2026-11-01','2026-11-30',%s)""", (tenant, org, period, opened))
        self.owner.execute("""INSERT INTO omnixat.expense_account_policy
            (tenant_id, organisation_id, account_id, eligible_for_drafts)
            VALUES (%s,%s,%s,%s)""", (tenant, org, account, eligible))

    def test_csv_expense_preview_rejects_unavailable_policy_and_scope(self):
        _, _, job, cells = self.prepare_csv_review()
        scope = (self.a, self.org, self.registration.id, job, cells[0])
        account, period = uuid4(), uuid4()
        other_org, other_period, other_account = uuid4(), uuid4(), uuid4()
        self.owner.execute("""INSERT INTO omnixat.organisations (tenant_id,id,display_name,created_by)
            VALUES (%s,%s,'Fictional other org','fixture'),(%s,%s,'Fictional other tenant org','fixture')""",
                           (self.a, other_org, self.b, self.org))
        self.configure_expense_policy(self.a, other_org, other_period, other_account)
        self.configure_expense_policy(self.b, self.org, period, account)
        context = ExpenseDraftContext("GBP", date(2026, 11, 30), account)
        with psycopg.connect(self.expense_preview_dsn, autocommit=True) as reader:
            def preview(ctx=context, selected=period, actor=self.actor):
                return prepare_csv_expense_draft(reader, actor, *scope, context=ctx, period_id=selected)

            with self.assertRaisesRegex(ValueError, "unavailable"):
                preview()  # Identical IDs provisioned in another tenant.
            self.configure_expense_policy(self.a, self.org, period, account, opened=False, eligible=False)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                preview()
            self.owner.execute("""UPDATE omnixat.expense_accounting_periods SET open_for_drafts=true
                WHERE tenant_id=%s AND organisation_id=%s AND id=%s""", (self.a, self.org, period))
            with self.assertRaisesRegex(ValueError, "unavailable"):
                preview()
            self.owner.execute("""UPDATE omnixat.expense_account_policy SET eligible_for_drafts=true
                WHERE tenant_id=%s AND organisation_id=%s AND account_id=%s""", (self.a, self.org, account))
            with self.assertRaises(EvidenceNotEligible):
                preview()  # End date passes policy; draft source is still required.
            for ctx, selected in (
                (context, other_period),
                (ExpenseDraftContext("GBP", date(2026, 11, 30), other_account), period),
                (ExpenseDraftContext("GBP", date(2026, 12, 1), account), period),
                (ExpenseDraftContext("USD", date(2026, 11, 30), account), period),
            ):
                with self.subTest(context=ctx, period=selected), self.assertRaises(ValueError):
                    preview(ctx, selected)
            for actor in (self.other, Principal("viewer", self.a, "viewer"),
                          Principal("agent", self.a, "editor", actor_kind="agent"),
                          Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"}))):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    preview(actor=actor)

    def test_expense_policy_constraints_and_preview_role_grants(self):
        period, account = uuid4(), uuid4()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.configure_expense_policy(self.b, self.org, period, account)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute("""INSERT INTO omnixat.expense_accounting_periods
                (tenant_id, organisation_id, id, starts_on, ends_on)
                VALUES (%s,%s,%s,'2026-12-01','2026-11-30')""", (self.a, self.org, period))
        self.owner.execute("""INSERT INTO omnixat.expense_accounting_periods
            (tenant_id, organisation_id, id, starts_on, ends_on)
            VALUES (%s,%s,%s,'2026-11-01','2026-11-30')""", (self.a, self.org, period))
        self.owner.execute("""INSERT INTO omnixat.expense_account_policy
            (tenant_id, organisation_id, account_id) VALUES (%s,%s,%s)""", (self.a, self.org, account))
        self.assertEqual(self.owner.execute("""SELECT p.open_for_drafts, a.eligible_for_drafts
            FROM omnixat.expense_accounting_periods p
            JOIN omnixat.expense_account_policy a USING (tenant_id, organisation_id)
            WHERE p.tenant_id=%s AND p.id=%s AND a.account_id=%s""", (self.a, period, account)).fetchone(),
                         (False, False))
        with psycopg.connect(self.expense_preview_dsn, autocommit=True) as reader:
            for statement in ("SELECT * FROM omnixat.expense_accounting_periods",
                              "UPDATE omnixat.expense_account_policy SET eligible_for_drafts=true"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    reader.execute(statement)
            with self.assertRaises(PermissionError):
                read_csv_draft_amount(reader, self.actor, self.a, self.org,
                                      self.registration.id, uuid4(), AmountCell("amount", 2, 2))
        with psycopg.connect(self.draft_reader_dsn, autocommit=True) as reader:
            with self.assertRaises(PermissionError):
                prepare_csv_expense_draft(
                    reader, self.actor, self.a, self.org, self.registration.id, uuid4(), AmountCell("amount", 2, 2),
                    context=ExpenseDraftContext("GBP", date(2026, 11, 30), account), period_id=period,
                )

    def expense_write_fixture(self, amount="12.340"):
        _, _, job, cells = self.prepare_csv_review()
        scope = (self.a, self.org, self.registration.id, job, cells[1])
        with psycopg.connect(self.answer_dsn, autocommit=True) as answer:
            store_csv_clarification(answer, self.actor, *scope, amount=amount)
        with psycopg.connect(self.draft_dsn, autocommit=True) as draft:
            create_csv_draft_amount(draft, self.actor, *scope)
        period, account = uuid4(), uuid4()
        self.configure_expense_policy(self.a, self.org, period, account)
        return scope, period, ExpenseDraftContext("GBP", date(2026, 11, 6), account)

    def test_expense_write_concurrent_retry_conflict_and_role_separation(self):
        scope, period, context = self.expense_write_fixture()
        start = Barrier(2)

        def create():
            with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
                start.wait(timeout=5)
                return create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: create(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(first.amount_pence, 1234)
        self.assertEqual(self.owner.execute("""
            SELECT id, evidence_id, job_id, field_name, currency, amount_pence, created_by
            FROM omnixat.csv_expense_drafts WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [(first.id, scope[2], scope[3], scope[4].field_name,
                                      "GBP", 1234, self.actor.user_id)])
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            changed = ExpenseDraftContext("GBP", date(2026, 11, 7), context.expense_account_id)
            with self.assertRaises(ExpenseDraftConflict):
                create_csv_expense_draft(writer, self.actor, *scope, context=changed, period_id=period)
            with self.assertRaises(PermissionError):
                create_csv_expense_draft(writer, self.other, *scope, context=context, period_id=period)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.csv_expense_drafts")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        with psycopg.connect(self.expense_preview_dsn, autocommit=True) as reader:
            with self.assertRaises(PermissionError):
                create_csv_expense_draft(reader, self.actor, *scope, context=context, period_id=period)

    def test_expense_write_refuses_fractional_pence_and_disabled_account(self):
        scope, period, context = self.expense_write_fixture("12.341")
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            with self.assertRaisesRegex(ValueError, "exact to a penny"):
                create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
            self.owner.execute("""UPDATE omnixat.expense_account_policy SET eligible_for_drafts=false
                WHERE tenant_id=%s AND organisation_id=%s AND account_id=%s""",
                               (self.a, self.org, context.expense_account_id))
            with self.assertRaisesRegex(ValueError, "unavailable"):
                create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.csv_expense_drafts WHERE tenant_id=%s",
                                           (self.a,)).fetchone(), (0,))

    def test_expense_write_holds_policy_and_scan_observations_until_commit(self):
        scope, period, context = self.expense_write_fixture()
        _, org, evidence, job, cell = scope
        claim = """INSERT INTO omnixat.evidence_scan_claims
            (tenant_id,evidence_id,policy_version,lease_token,expires_at)
            VALUES (%s,%s,'fictional-v1',%s,clock_timestamp() + interval '1 minute')"""
        claim_args = (self.a, evidence, uuid4())
        self.owner.execute(claim, claim_args)
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            with self.assertRaises(EvidenceNotEligible):
                create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
            self.owner.execute("DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s AND evidence_id=%s",
                               (self.a, evidence))
            with writer.transaction():
                writer.execute("SELECT set_config('omnixat.tenant_id', %s, true)", (self.a,))
                self.assertEqual(writer.execute("""
                    SELECT outcome FROM omnixat_extraction.create_csv_expense_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (org, evidence, job, cell.field_name, cell.row, cell.column, period,
                      context.expense_account_id, context.accounting_date, context.currency,
                      self.actor.user_id)).fetchone(), ("stored",))
                for statement, args in (
                    ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'", ()),
                    ("UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s", (self.a,)),
                    ("UPDATE omnixat.expense_account_policy SET eligible_for_drafts=false WHERE tenant_id=%s", (self.a,)),
                    (claim, claim_args),
                    ("""INSERT INTO omnixat.evidence_scan_verdicts
                        (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                        VALUES (%s,%s,%s,%s,'fictional-v1','blocked')""",
                     (self.a, evidence, sha256(self.original).digest(), len(self.original))),
                ):
                    with self.subTest(statement=statement), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='100ms'")
                            self.owner.execute(statement, args)
            self.owner.execute(claim, claim_args)
            with self.assertRaises(EvidenceNotEligible):
                create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)

    def test_expense_review_shows_exact_saved_context_and_source_in_scope(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            receipt = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
            with self.assertRaises(PermissionError):
                read_csv_expense_draft(writer, self.actor, self.a, self.org, receipt.id)
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.expense_reader_dsn, autocommit=True) as reader:
            review = read_csv_expense_draft(reader, viewer, self.a, self.org, receipt.id)
            self.assertEqual((review.receipt, review.created_by, review.context, review.period_id),
                             (receipt, self.actor.user_id, context, period))
            source = review.source
            self.assertEqual((source.receipt.evidence_id, source.receipt.job_id, source.receipt.cell), scope[2:])
            self.assertEqual(source.receipt.source_kind, "clarified")
            self.assertEqual(source.amount.as_tuple(), Decimal("12.340").as_tuple())
            self.assertEqual(source.policy_version, "fictional-v1")
            self.assertEqual(source.content_sha256, sha256(self.original).hexdigest())
            for actor, tenant, org, draft in (
                (viewer, self.a, uuid4(), receipt.id),
                (viewer, self.a, self.org, uuid4()),
                (self.other, self.b, self.org, receipt.id),
            ):
                with self.subTest(tenant=tenant, org=org, draft=draft), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Expense draft is unavailable$",
                ):
                    read_csv_expense_draft(reader, actor, tenant, org, draft)
            for actor in (
                self.other, Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
                Principal("staff", self.a, "viewer", staff_role="platform_owner"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    read_csv_expense_draft(reader, actor, self.a, self.org, receipt.id)
            with self.assertRaises(PermissionError):
                create_csv_expense_draft(reader, self.actor, *scope, context=context, period_id=period)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.csv_expense_drafts")

    def test_expense_review_withholds_draft_when_policy_or_amount_is_invalid(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            receipt = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        with psycopg.connect(self.expense_reader_dsn, autocommit=True) as reader:
            def read():
                return read_csv_expense_draft(reader, self.actor, self.a, self.org, receipt.id)

            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                read()
            self.set_active_policy("fictional-v1")
            for table, identifier, flag, value in (
                ("expense_accounting_periods", "id", "open_for_drafts", period),
                ("expense_account_policy", "account_id", "eligible_for_drafts", context.expense_account_id),
            ):
                update = sql.SQL("UPDATE omnixat.{} SET {}=%s WHERE tenant_id=%s AND {}=%s").format(
                    sql.Identifier(table), sql.Identifier(flag), sql.Identifier(identifier),
                )
                self.owner.execute(update, (False, self.a, value))
                with self.subTest(table=table), self.assertRaises(EvidenceNotEligible):
                    read()
                self.owner.execute(update, (True, self.a, value))
            self.assertEqual(read().receipt, receipt)
            self.owner.execute("UPDATE omnixat.csv_expense_drafts SET amount_pence=1 WHERE tenant_id=%s AND id=%s",
                               (self.a, receipt.id))
            with self.assertRaises(EvidenceNotEligible):
                read()

    def configure_funding_source(self, tenant, organisation, kind, *, eligible=True):
        source, payer = uuid4(), uuid4()
        self.owner.execute("""INSERT INTO omnixat.expense_funding_sources
            (tenant_id,organisation_id,id,payer_id,funding_kind,eligible_for_drafts)
            VALUES (%s,%s,%s,%s,%s,%s)""", (tenant, organisation, source, payer, kind, eligible))
        return {"funding_source_id": source, "payer_id": payer}

    def test_expense_funding_records_explicit_personal_choice_and_replays_concurrently(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        personal = self.configure_funding_source(self.a, self.org, "personal_funds")
        business = self.configure_funding_source(self.a, self.org, "business_funds")
        start = Barrier(2)

        def record():
            with psycopg.connect(self.funding_dsn, autocommit=True) as db:
                start.wait(timeout=5)
                return record_expense_funding_context(db, self.actor, self.a, self.org, draft.id, **personal)

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual((first.draft_id, first.funding_source_id, first.payer_id, first.funding_kind),
                         (draft.id, personal["funding_source_id"], personal["payer_id"], "personal_funds"))
        self.assertEqual(self.owner.execute("""
            SELECT recorded_by, recorded_at FROM omnixat.expense_funding_context WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [(self.actor.user_id, first.recorded_at)])
        with psycopg.connect(self.funding_dsn, autocommit=True) as db:
            with self.assertRaises(ExpenseFundingConflict):
                record_expense_funding_context(db, self.actor, self.a, self.org, draft.id, **business)
            other_actor = Principal("fictional-editor-two", self.a, "editor")
            with self.assertRaises(ExpenseFundingConflict):
                record_expense_funding_context(db, other_actor, self.a, self.org, draft.id, **personal)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM omnixat.expense_funding_context")
        with psycopg.connect(self.expense_reader_dsn, autocommit=True) as db:
            with self.assertRaises(PermissionError):
                record_expense_funding_context(db, self.actor, self.a, self.org, draft.id, **personal)

    def test_expense_funding_requires_matching_eligible_source_and_current_draft(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        other_org = uuid4()
        self.owner.execute("""INSERT INTO omnixat.organisations (tenant_id,id,display_name,created_by)
            VALUES (%s,%s,'Fictional other org','fixture'),(%s,%s,'Fictional other tenant','fixture')""",
                           (self.a, other_org, self.b, self.org))
        wrong_org = self.configure_funding_source(self.a, other_org, "business_funds")
        wrong_tenant = self.configure_funding_source(self.b, self.org, "business_funds")
        disabled = self.configure_funding_source(self.a, self.org, "business_funds", eligible=False)
        business = self.configure_funding_source(self.a, self.org, "business_funds")
        with psycopg.connect(self.funding_dsn, autocommit=True) as db:
            for tenant, org, selection, actor in (
                (self.a, self.org, wrong_org, self.actor),
                (self.a, other_org, wrong_org, self.actor),
                (self.a, self.org, wrong_tenant, self.actor),
                (self.b, self.org, wrong_tenant, self.other),
                (self.a, self.org, disabled, self.actor),
                (self.a, self.org, business | {"payer_id": uuid4()}, self.actor),
            ):
                with self.subTest(tenant=tenant, org=org, selection=selection), self.assertRaises(EvidenceNotEligible):
                    record_expense_funding_context(db, actor, tenant, org, draft.id, **selection)
            for actor in (
                Principal("viewer", self.a, "viewer"),
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    record_expense_funding_context(db, actor, self.a, self.org, draft.id, **business)
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                record_expense_funding_context(db, self.actor, self.a, self.org, draft.id, **business)
            self.assertEqual(self.owner.execute(
                "SELECT count(*) FROM omnixat.expense_funding_context WHERE tenant_id=%s", (self.a,),
            ).fetchone(), (0,))
            self.set_active_policy("fictional-v1")
            result = record_expense_funding_context(db, self.actor, self.a, self.org, draft.id, **business)
            self.assertEqual(result.funding_kind, "business_funds")
            self.owner.execute("""UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false
                WHERE tenant_id=%s AND organisation_id=%s AND id=%s""",
                               (self.a, self.org, business["funding_source_id"]))
            with self.assertRaises(EvidenceNotEligible):
                record_expense_funding_context(db, self.actor, self.a, self.org, draft.id, **business)

    def test_expense_funding_review_distinguishes_missing_disabled_and_unavailable(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        selection = self.configure_funding_source(self.a, self.org, "personal_funds")
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.funding_reader_dsn, autocommit=True) as reader:
            def review():
                return read_expense_funding_context(reader, viewer, self.a, self.org, draft.id)

            self.assertIsNone(review())
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.set_active_policy("fictional-v1")
            with psycopg.connect(self.funding_dsn, autocommit=True) as writer:
                saved = record_expense_funding_context(writer, self.actor, self.a, self.org, draft.id, **selection)
            result = review()
            self.assertEqual((result.receipt, result.recorded_by, result.source_eligible),
                             (saved, self.actor.user_id, True))
            self.owner.execute("""UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false
                WHERE tenant_id=%s AND organisation_id=%s AND id=%s""",
                               (self.a, self.org, selection["funding_source_id"]))
            result = review()
            self.assertEqual(result.receipt, saved)
            self.assertFalse(result.source_eligible)
            self.owner.execute("""UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false
                WHERE tenant_id=%s AND organisation_id=%s AND id=%s""", (self.a, self.org, period))
            with self.assertRaises(EvidenceNotEligible):
                review()

    def test_expense_funding_review_requires_scope_and_dedicated_read_grants(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        selection = self.configure_funding_source(self.a, self.org, "business_funds")
        with psycopg.connect(self.funding_dsn, autocommit=True) as writer:
            record_expense_funding_context(writer, self.actor, self.a, self.org, draft.id, **selection)
            with self.assertRaises(PermissionError):
                read_expense_funding_context(writer, self.actor, self.a, self.org, draft.id)
        with psycopg.connect(self.funding_reader_dsn, autocommit=True) as reader:
            for actor, tenant, org, receipt_id in (
                (self.actor, self.a, uuid4(), draft.id),
                (self.actor, self.a, self.org, uuid4()),
                (self.other, self.b, self.org, draft.id),
            ):
                with self.subTest(tenant=tenant, org=org, receipt_id=receipt_id), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Expense draft is unavailable$",
                ):
                    read_expense_funding_context(reader, actor, tenant, org, receipt_id)
            for actor in (
                self.other, Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
                Principal("staff", self.a, "viewer", staff_role="platform_owner"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    read_expense_funding_context(reader, actor, self.a, self.org, draft.id)
            with self.assertRaises(PermissionError):
                record_expense_funding_context(reader, self.actor, self.a, self.org, draft.id, **selection)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_funding_context")

    def configure_counterpart(self, tenant, organisation, source, account, *, enable=False):
        self.owner.execute("""INSERT INTO omnixat.expense_counterpart_policy
            (tenant_id,organisation_id,funding_source_id,account_id) VALUES (%s,%s,%s,%s)""",
                           (tenant, organisation, source, account))
        if enable:
            self.owner.execute("""UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=true
                WHERE tenant_id=%s AND organisation_id=%s AND funding_source_id=%s AND account_id=%s""",
                               (tenant, organisation, source, account))

    def test_journal_preview_balances_exact_source_amount_and_rechecks_policy(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        selection = self.configure_funding_source(self.a, self.org, "personal_funds")
        source = selection["funding_source_id"]
        account = uuid4()
        self.configure_counterpart(self.a, self.org, source, account)
        with psycopg.connect(self.journal_preview_dsn, autocommit=True) as reader:
            def preview():
                return prepare_expense_journal_preview(reader, self.actor, self.a, self.org, draft.id,
                                                       counterpart_account_id=account)
            with self.assertRaises(EvidenceNotEligible):
                preview()  # No recorded funding yet.
            with psycopg.connect(self.funding_dsn, autocommit=True) as writer:
                record_expense_funding_context(writer, self.actor, self.a, self.org, draft.id, **selection)
            with self.assertRaises(EvidenceNotEligible):
                preview()  # Counterpart policy defaults to disabled.
            self.owner.execute("""UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=true
                WHERE tenant_id=%s AND organisation_id=%s AND funding_source_id=%s AND account_id=%s""",
                               (self.a, self.org, source, account))
            result = preview()
            self.assertEqual((result.draft_id, result.funding_source_id, result.currency,
                              result.accounting_date, result.period_id),
                             (draft.id, source, "GBP", context.accounting_date, period))
            self.assertEqual((result.evidence_id, result.extraction_job_id, result.source_cell), scope[2:])
            self.assertEqual(result.content_sha256, sha256(self.original).hexdigest())
            self.assertEqual(result.scan_policy_version, "fictional-v1")
            self.assertEqual([(x.account_id, x.side, x.amount_pence) for x in result.lines],
                             [(context.expense_account_id, "debit", 1234), (account, "credit", 1234)])
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                preview()
            self.set_active_policy("fictional-v1")
            self.owner.execute("""UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false
                WHERE tenant_id=%s AND organisation_id=%s AND id=%s""", (self.a, self.org, source))
            with self.assertRaises(EvidenceNotEligible):
                preview()

    def test_journal_preview_rejects_wrong_source_scope_same_account_and_roles(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        selection = self.configure_funding_source(self.a, self.org, "business_funds")
        source = selection["funding_source_id"]
        another = self.configure_funding_source(self.a, self.org, "business_funds")["funding_source_id"]
        with psycopg.connect(self.funding_dsn, autocommit=True) as writer:
            record_expense_funding_context(writer, self.actor, self.a, self.org, draft.id, **selection)
        wrong_source, eligible = uuid4(), uuid4()
        self.configure_counterpart(self.a, self.org, another, wrong_source, enable=True)
        self.configure_counterpart(self.a, self.org, source, context.expense_account_id, enable=True)
        self.configure_counterpart(self.a, self.org, source, eligible, enable=True)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.configure_counterpart(self.b, self.org, source, eligible, enable=True)
        with psycopg.connect(self.journal_preview_dsn, autocommit=True) as reader:
            for actor, tenant, org, account in (
                (self.actor, self.a, self.org, wrong_source),
                (self.actor, self.a, self.org, context.expense_account_id),
                (self.actor, self.a, uuid4(), eligible),
                (self.other, self.b, self.org, eligible),
            ):
                with self.subTest(tenant=tenant, org=org, account=account), self.assertRaises(EvidenceNotEligible):
                    prepare_expense_journal_preview(reader, actor, tenant, org, draft.id, counterpart_account_id=account)
            for actor in (
                Principal("viewer", self.a, "viewer"),
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    prepare_expense_journal_preview(reader, actor, self.a, self.org, draft.id,
                                                    counterpart_account_id=eligible)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_counterpart_policy")
        with psycopg.connect(self.funding_dsn, autocommit=True) as writer:
            with self.assertRaises(PermissionError):
                prepare_expense_journal_preview(writer, self.actor, self.a, self.org, draft.id,
                                                counterpart_account_id=eligible)

    def journal_write_fixture(self):
        scope, period, context = self.expense_write_fixture()
        with psycopg.connect(self.expense_writer_dsn, autocommit=True) as writer:
            draft = create_csv_expense_draft(writer, self.actor, *scope, context=context, period_id=period)
        selection = self.configure_funding_source(self.a, self.org, "business_funds")
        with psycopg.connect(self.funding_dsn, autocommit=True) as writer:
            record_expense_funding_context(writer, self.actor, self.a, self.org, draft.id, **selection)
        source = selection["funding_source_id"]
        account = uuid4()
        self.configure_counterpart(self.a, self.org, source, account, enable=True)
        return scope, period, context, draft, source, account

    def test_journal_write_persists_exact_snapshot_and_replays_concurrently(self):
        _, period, context, draft, source, account = self.journal_write_fixture()
        start = Barrier(2)

        def save():
            with psycopg.connect(self.journal_writer_dsn, autocommit=True) as writer:
                start.wait(timeout=5)
                return create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                                    counterpart_account_id=account)

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: save(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.owner.execute("""
            SELECT id, expense_draft_id, expense_account_id, counterpart_account_id, funding_source_id,
                   amount_pence, currency, accounting_date, period_id, scan_policy_version,
                   content_sha256, created_by, created_at
            FROM omnixat.expense_journal_drafts WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [
            (first.id, draft.id, context.expense_account_id, account, source, 1234, "GBP",
             context.accounting_date, period, "fictional-v1", sha256(self.original).digest(),
             self.actor.user_id, first.created_at),
        ])
        other_account = uuid4()
        self.configure_counterpart(self.a, self.org, source, other_account, enable=True)
        with psycopg.connect(self.journal_writer_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalConflict):
                create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                             counterpart_account_id=other_account)
            with self.assertRaises(EvidenceNotEligible):
                create_expense_journal_draft(writer, self.other, self.b, self.org, draft.id,
                                             counterpart_account_id=account)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_drafts")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                             counterpart_account_id=account)
        with psycopg.connect(self.journal_preview_dsn, autocommit=True) as reader:
            with self.assertRaises(PermissionError):
                create_expense_journal_draft(reader, self.actor, self.a, self.org, draft.id,
                                             counterpart_account_id=account)

    def test_journal_write_holds_eligibility_through_commit(self):
        scope, period, _, draft, source, account = self.journal_write_fixture()
        evidence = scope[2]
        changes = (
            ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'", ()),
            ("UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s AND id=%s",
             (self.a, period)),
            ("UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE tenant_id=%s AND id=%s",
             (self.a, source)),
            ("""UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false
                WHERE tenant_id=%s AND funding_source_id=%s AND account_id=%s""", (self.a, source, account)),
            ("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                VALUES (%s,%s,%s,%s,'fictional-v1','blocked')""",
             (self.a, evidence, sha256(self.original).digest(), len(self.original))),
        )
        with psycopg.connect(self.journal_writer_dsn, autocommit=True) as writer:
            with writer.transaction():
                writer.execute("SELECT set_config('omnixat.tenant_id', %s, true)", (self.a,))
                self.assertEqual(writer.execute("""
                    SELECT outcome FROM omnixat_extraction.create_expense_journal_draft(%s,%s,%s,%s)
                """, (self.org, draft.id, account, self.actor.user_id)).fetchone(), ("stored",))
                for statement, args in changes:
                    with self.subTest(statement=statement), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='100ms'")
                            self.owner.execute(statement, args)
            self.owner.execute(*changes[-1])
            with self.assertRaises(EvidenceNotEligible):
                create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                             counterpart_account_id=account)

    def test_journal_review_reads_saved_lines_and_provenance_with_scoped_grants(self):
        scope, period, context, draft, source, account = self.journal_write_fixture()
        with psycopg.connect(self.journal_writer_dsn, autocommit=True) as writer:
            receipt = create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                                   counterpart_account_id=account)
            with self.assertRaises(PermissionError):
                read_expense_journal_draft(writer, self.actor, self.a, self.org, receipt.id)
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            result = read_expense_journal_draft(reader, viewer, self.a, self.org, receipt.id)
            self.assertEqual((result.receipt, result.created_by), (receipt, self.actor.user_id))
            j = result.journal
            self.assertEqual((j.draft_id, j.funding_source_id, j.currency, j.accounting_date, j.period_id),
                             (draft.id, source, "GBP", context.accounting_date, period))
            self.assertEqual((j.evidence_id, j.extraction_job_id, j.source_cell), scope[2:])
            self.assertEqual(j.content_sha256, sha256(self.original).hexdigest())
            self.assertEqual(j.scan_policy_version, "fictional-v1")
            self.assertEqual([(line.account_id, line.side, line.amount_pence) for line in j.lines],
                             [(context.expense_account_id, "debit", 1234), (account, "credit", 1234)])
            for actor, tenant, org, journal in (
                (viewer, self.a, uuid4(), receipt.id),
                (viewer, self.a, self.org, uuid4()),
                (self.other, self.b, self.org, receipt.id),
            ):
                with self.subTest(tenant=tenant, org=org, journal=journal), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Journal draft is unavailable$",
                ):
                    read_expense_journal_draft(reader, actor, tenant, org, journal)
            for actor in (
                self.other, Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
                Principal("staff", self.a, "viewer", staff_role="platform_owner"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    read_expense_journal_draft(reader, actor, self.a, self.org, receipt.id)
            with self.assertRaises(PermissionError):
                create_expense_journal_draft(reader, self.actor, self.a, self.org, draft.id,
                                             counterpart_account_id=account)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_journal_drafts")

    def test_journal_review_withholds_stale_or_mismatched_saved_snapshot(self):
        _, _, _, draft, source, account = self.journal_write_fixture()
        with psycopg.connect(self.journal_writer_dsn, autocommit=True) as writer:
            receipt = create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                                   counterpart_account_id=account)
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            def review():
                return read_expense_journal_draft(reader, self.actor, self.a, self.org, receipt.id)

            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.set_active_policy("fictional-v1")
            self.assertEqual(review().receipt, receipt)
            update_policy = """UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=%s
                WHERE tenant_id=%s AND organisation_id=%s AND funding_source_id=%s AND account_id=%s"""
            policy_scope = (self.a, self.org, source, account)
            self.owner.execute(update_policy, (False, *policy_scope))
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.owner.execute(update_policy, (True, *policy_scope))
            self.assertEqual(review().receipt, receipt)
            self.owner.execute("""UPDATE omnixat.expense_journal_drafts SET amount_pence=1235
                WHERE tenant_id=%s AND id=%s""", (self.a, receipt.id))
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.owner.execute("""UPDATE omnixat.expense_journal_drafts
                SET amount_pence=1234, content_sha256=%s WHERE tenant_id=%s AND id=%s""",
                               (sha256(b"Different fictional document").digest(), self.a, receipt.id))
            with self.assertRaises(EvidenceNotEligible):
                review()
