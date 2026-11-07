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
from omnixat_core.postgres import tenant_records
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
    ExpenseJournalClarification, ExpenseJournalClarificationConflict, ExpenseJournalConflict,
    ExpenseJournalDecisionConflict, ExpenseJournalEvidenceLinkConflict, ExpenseJournalSupportingEvidence,
    create_expense_journal_draft, create_expense_journal_amount_correction,
    ExpenseJournalAmountCorrectionConflict, link_expense_journal_clarification_evidence, record_expense_journal_clarification,
    prepare_expense_journal_preview, preview_expense_journal_amount_correction,
    read_expense_journal_amount_correction, read_expense_journal_decisions, read_expense_journal_draft,
    record_expense_journal_amount_correction_decision, ExpenseJournalAmountCorrectionDecisionConflict,
    read_expense_journal_amount_correction_decisions, preview_expense_journal_replacement,
    create_expense_journal_replacement, ExpenseJournalReplacementConflict, read_expense_journal_replacement,
    select_expense_journal_replacement, ExpenseJournalSelectionConflict, read_current_expense_journal,
    ExpenseJournalCorrectionConflict, record_expense_journal_correction, record_expense_journal_decision,
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
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_review(uuid,uuid) TO {}"
        ).format(journal_review))
        cls.journal_review_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                              user=journal_review_role, password=password)

        decision_role = cls.role + "_decision_writer"
        decision_writer = sql.Identifier(decision_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(decision_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, decision_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(decision_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.record_expense_journal_decision"
            "(uuid,uuid,bytea,text,text) TO {}"
        ).format(decision_writer))
        cls.decision_writer_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=decision_role, password=password)

        decision_reader_role = cls.role + "_decision_reader"
        decision_reader = sql.Identifier(decision_reader_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(decision_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, decision_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(decision_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_decisions_with_evidence"
            "(uuid,uuid,bytea,text,integer) TO {}"
        ).format(decision_reader))
        cls.decision_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=decision_reader_role, password=password)

        correction_role = cls.role + "_correction"
        correction_writer = sql.Identifier(correction_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(correction_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, correction_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(correction_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.record_expense_journal_correction"
            "(uuid,uuid,bytea,text,text) TO {}"
        ).format(correction_writer))
        cls.correction_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                          user=correction_role, password=password)

        clarification_role = cls.role + "_clarification"
        clarification_writer = sql.Identifier(clarification_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(clarification_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, clarification_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(clarification_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.record_expense_journal_clarification"
            "(uuid,uuid,bytea,text,text,text,text) TO {}"
        ).format(clarification_writer))
        cls.clarification_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                             user=clarification_role, password=password)

        link_role = cls.role + "_evidence_link"
        link_writer = sql.Identifier(link_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(link_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, link_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(link_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.link_expense_journal_clarification_evidence"
            "(uuid,uuid,bytea,text,uuid,text) TO {}"
        ).format(link_writer))
        cls.evidence_link_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                              user=link_role, password=password)

        correction_preview_role = cls.role + "_amount_preview"
        correction_preview = sql.Identifier(correction_preview_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(correction_preview, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, correction_preview_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(correction_preview))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_amount_correction"
            "(uuid,uuid,bytea,uuid,text,integer,integer) TO {}"
        ).format(correction_preview))
        cls.amount_preview_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=correction_preview_role, password=password)

        amount_proposal_role = cls.role + "_amount_proposal"
        amount_proposal = sql.Identifier(amount_proposal_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(amount_proposal, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, amount_proposal_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(amount_proposal))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.create_expense_journal_amount_correction"
            "(uuid,uuid,bytea,uuid,text,integer,integer,text,text) TO {}"
        ).format(amount_proposal))
        cls.amount_proposal_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                user=amount_proposal_role, password=password)

        proposal_reader_role = cls.role + "_proposal_reader"
        proposal_reader = sql.Identifier(proposal_reader_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(proposal_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, proposal_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(proposal_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_amount_correction_review"
            "(uuid,uuid) TO {}"
        ).format(proposal_reader))
        cls.proposal_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                               user=proposal_reader_role, password=password)

        proposal_decision_role = cls.role + "_proposal_decision"
        proposal_decision_writer = sql.Identifier(proposal_decision_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(proposal_decision_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, proposal_decision_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(proposal_decision_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.record_expense_journal_amount_correction_decision"
            "(uuid,uuid,bytea,text,text) TO {}"
        ).format(proposal_decision_writer))
        cls.proposal_decision_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                 user=proposal_decision_role, password=password)

        proposal_history_role = cls.role + "_proposal_history"
        proposal_history_reader = sql.Identifier(proposal_history_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(proposal_history_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, proposal_history_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(proposal_history_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_amount_correction_decisions"
            "(uuid,uuid,bytea,text,integer) TO {}"
        ).format(proposal_history_reader))
        cls.proposal_history_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                user=proposal_history_role, password=password)

        replacement_preview_role = cls.role + "_replacement_preview"
        replacement_preview = sql.Identifier(replacement_preview_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(replacement_preview, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, replacement_preview_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(replacement_preview))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_expense_journal_replacement_preview"
            "(uuid,uuid,bytea,text) TO {}"
        ).format(replacement_preview))
        cls.replacement_preview_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                    user=replacement_preview_role, password=password)

        replacement_writer_role = cls.role + "_replacement_writer"
        replacement_writer = sql.Identifier(replacement_writer_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(replacement_writer, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, replacement_writer_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(replacement_writer))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.create_expense_journal_replacement"
            "(uuid,uuid,bytea,text,text) TO {}"
        ).format(replacement_writer))
        cls.replacement_writer_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                   user=replacement_writer_role, password=password)

        replacement_reader_role = cls.role + "_replacement_reader"
        replacement_reader = sql.Identifier(replacement_reader_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(replacement_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, replacement_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(replacement_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_saved_expense_journal_replacement"
            "(uuid,uuid) TO {}"
        ).format(replacement_reader))
        cls.replacement_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                   user=replacement_reader_role, password=password)

        selection_role = cls.role + "_replacement_selector"
        selector = sql.Identifier(selection_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(selector, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, selection_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(selector))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.select_expense_journal_replacement"
            "(uuid,uuid,uuid,bytea,text) TO {}"
        ).format(selector))
        cls.replacement_selector_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                     user=selection_role, password=password)

        current_reader_role = cls.role + "_current_journal_reader"
        current_reader = sql.Identifier(current_reader_role)
        password = uuid4().hex
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                          .format(current_reader, sql.Literal(password)))
        cls.addClassCleanup(cls.drop_role, current_reader_role)
        cls.owner.execute(sql.SQL("GRANT USAGE ON SCHEMA omnixat_extraction TO {}").format(current_reader))
        cls.owner.execute(sql.SQL(
            "GRANT EXECUTE ON FUNCTION omnixat_extraction.read_current_expense_journal(uuid,uuid) TO {}"
        ).format(current_reader))
        cls.current_journal_reader_dsn = make_conninfo(cls.admin.info.dsn, dbname=cls.database,
                                                       user=current_reader_role, password=password)

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

    def journal_decision_fixture(self):
        _, _, _, draft, _, account = self.journal_write_fixture()
        with psycopg.connect(self.journal_writer_dsn, autocommit=True) as writer:
            receipt = create_expense_journal_draft(writer, self.actor, self.a, self.org, draft.id,
                                                   counterpart_account_id=account)
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            first = read_expense_journal_draft(reader, self.actor, self.a, self.org, receipt.id)
            reader.execute("SET TIME ZONE 'Pacific/Auckland'")
            second = read_expense_journal_draft(reader, self.actor, self.a, self.org, receipt.id)
            self.assertEqual(first.snapshot_sha256, second.snapshot_sha256)
        return first

    def test_journal_decision_is_attributed_and_replays_concurrently(self):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        barrier = Barrier(2)

        def record():
            with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
                barrier.wait(timeout=5)
                return record_expense_journal_decision(writer, self.actor, self.a, self.org, journal,
                                                       snapshot_sha256=digest, decision="reviewed")

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual((first.journal_id, first.snapshot_sha256, first.decision, first.reviewer_id),
                         (journal, digest, "reviewed", self.actor.user_id))
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalDecisionConflict):
                record_expense_journal_decision(writer, self.actor, self.a, self.org, journal,
                                                snapshot_sha256=digest, decision="changes_requested")
            other = Principal("fictional-second-reviewer", self.a, "editor")
            result = record_expense_journal_decision(writer, other, self.a, self.org, journal,
                                                     snapshot_sha256=digest, decision="changes_requested")
            self.assertEqual(result.reviewer_id, other.user_id)
        self.assertCountEqual(self.owner.execute("""
            SELECT reviewer_id, decision, snapshot_sha256
            FROM omnixat.expense_journal_review_decisions WHERE tenant_id=%s AND journal_id=%s
        """, (self.a, journal)).fetchall(), [
            (self.actor.user_id, "reviewed", bytes.fromhex(digest)),
            (other.user_id, "changes_requested", bytes.fromhex(digest)),
        ])

    def test_journal_decision_refuses_stale_snapshot_scope_and_nonhuman_reviewers(self):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            def decide(actor=self.actor, tenant=self.a, org=self.org, expected=digest):
                return record_expense_journal_decision(writer, actor, tenant, org, journal,
                                                       snapshot_sha256=expected, decision="reviewed")

            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    decide(actor=actor)
            with self.assertRaises(EvidenceNotEligible):
                decide(actor=self.other, tenant=self.b)
            with self.assertRaises(EvidenceNotEligible):
                decide(org=uuid4())
            with self.assertRaises(ValueError):
                decide(expected="malformed")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                decide()
            self.set_active_policy("fictional-v1")
            self.owner.execute("""UPDATE omnixat.expense_journal_drafts SET created_by='fictional-corrected-author'
                WHERE tenant_id=%s AND id=%s""", (self.a, journal))
            with self.assertRaises(EvidenceNotEligible):
                decide()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_review_decisions")
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_review_decisions WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            with self.assertRaises(PermissionError):
                record_expense_journal_decision(reader, self.actor, self.a, self.org, journal,
                                                snapshot_sha256=digest, decision="reviewed")

    def test_journal_decision_read_pages_only_current_snapshot_observations(self):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.decision_reader_dsn, autocommit=True) as reader:
            def page(cursor=None):
                return read_expense_journal_decisions(reader, viewer, self.a, self.org, journal,
                                                      snapshot_sha256=digest, page_size=1, after_reviewer=cursor)

            empty_page = page()
            self.assertEqual((empty_page.decisions, empty_page.next_after_reviewer), ((), None))
            self.assertEqual(empty_page.follow_up_questions, ())
            earlier = Principal("fictional-reviewer-a", self.a, "editor")
            later = Principal("fictional-reviewer-z", self.a, "editor")
            with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
                second = record_expense_journal_decision(writer, later, self.a, self.org, journal,
                                                         snapshot_sha256=digest, decision="changes_requested")
                first = record_expense_journal_decision(writer, earlier, self.a, self.org, journal,
                                                        snapshot_sha256=digest, decision="changes_requested")
            with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
                correction = record_expense_journal_correction(
                    writer, later, self.a, self.org, journal, snapshot_sha256=digest, reason="account",
                )
            previous_digest = sha256(b"fictional previous snapshot").digest()
            old_scope = (self.a, self.org, journal, previous_digest, earlier.user_id)
            self.owner.execute("""INSERT INTO omnixat.expense_journal_review_decisions
                (tenant_id,organisation_id,journal_id,snapshot_sha256,reviewer_id,decision)
                VALUES (%s,%s,%s,%s,%s,'changes_requested')""", old_scope)
            self.owner.execute("""INSERT INTO omnixat.expense_journal_correction_requests
                (tenant_id,organisation_id,journal_id,snapshot_sha256,reviewer_id,reason)
                VALUES (%s,%s,%s,%s,%s,'account')""", old_scope)
            self.owner.execute("""INSERT INTO omnixat.expense_journal_clarification_answers
                (tenant_id,organisation_id,journal_id,snapshot_sha256,reviewer_id,reason,answer,answered_by)
                VALUES (%s,%s,%s,%s,%s,'account','Fictional old answer.','fictional-old-respondent')""", old_scope)
            first_page = page()
            self.assertEqual((first_page.decisions, first_page.next_after_reviewer), ((first,), earlier.user_id))
            self.assertEqual(first_page.corrections, ())
            self.assertEqual(first_page.follow_up_questions, ())
            second_page = page(first_page.next_after_reviewer)
            self.assertEqual((second_page.decisions, second_page.next_after_reviewer), ((second,), None))
            self.assertEqual(second_page.corrections, (correction,))
            self.assertEqual(tuple(question.reason for question in second_page.follow_up_questions), ("account",))
            self.assertEqual(second_page.answers, ())
            with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
                receipt = record_expense_journal_clarification(
                    writer, self.actor, self.a, self.org, journal, snapshot_sha256=digest,
                    correction_reviewer_id=later.user_id, reason="account", answer="Fictional office supplies.",
                )
            self.assertEqual(page().answers, ())
            answered_page = page(first_page.next_after_reviewer)
            self.assertEqual(answered_page.answers, (ExpenseJournalClarification(receipt, "Fictional office supplies."),))
            self.assertEqual(answered_page.follow_up_questions, ())
            with psycopg.connect(self.evidence_link_dsn, autocommit=True) as writer:
                link = link_expense_journal_clarification_evidence(
                    writer, self.actor, self.a, self.org, journal, snapshot_sha256=digest,
                    reason="account", evidence_id=self.registration.id,
                )
            with reader.transaction():
                reader.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
                raw_page = reader.execute("""
                    SELECT reviewer_id, evidence_id
                    FROM omnixat_extraction.read_expense_journal_decisions_with_evidence(%s,%s,%s,NULL,1)
                """, (self.org, journal, bytes.fromhex(digest))).fetchall()
                self.assertEqual(raw_page, [(earlier.user_id, None), (later.user_id, None)])
            linked_page = page(first_page.next_after_reviewer)
            self.assertEqual(linked_page.answers[0].supporting_evidence, ExpenseJournalSupportingEvidence(link, True))
            self.assertEqual(page(later.user_id).decisions, ())
            self.owner.execute("""UPDATE omnixat.expense_journal_drafts SET created_by='fictional-other-author'
                WHERE tenant_id=%s AND id=%s""", (self.a, journal))
            with self.assertRaises(EvidenceNotEligible):
                page(first_page.next_after_reviewer)

    def test_journal_decision_read_denies_wrong_scope_grants_and_stale_policy(self):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        with psycopg.connect(self.decision_reader_dsn, autocommit=True) as reader:
            for actor, tenant, org, receipt, expected in (
                (self.other, self.b, self.org, journal, digest),
                (self.actor, self.a, uuid4(), journal, digest),
                (self.actor, self.a, self.org, uuid4(), digest),
                (self.actor, self.a, self.org, journal, "0" * 64),
            ):
                with self.subTest(tenant=tenant, org=org, journal=receipt), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Journal snapshot is unavailable$",
                ):
                    read_expense_journal_decisions(reader, actor, tenant, org, receipt, snapshot_sha256=expected)
            for actor in (
                Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    read_expense_journal_decisions(reader, actor, self.a, self.org, journal, snapshot_sha256=digest)
            with self.assertRaises(ValueError):
                read_expense_journal_decisions(reader, self.actor, self.a, self.org, journal,
                                               snapshot_sha256=digest, page_size=101)
            with self.assertRaises(PermissionError):
                record_expense_journal_decision(reader, self.actor, self.a, self.org, journal,
                                                snapshot_sha256=digest, decision="reviewed")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_journal_review_decisions")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_journal_correction_requests")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_journal_clarification_answers")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_journal_clarification_evidence")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)",
                               (self.org, self.registration.id))
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                read_expense_journal_decisions(reader, self.actor, self.a, self.org, journal, snapshot_sha256=digest)
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            with self.assertRaises(PermissionError):
                read_expense_journal_decisions(writer, self.actor, self.a, self.org, journal, snapshot_sha256=digest)

    def test_journal_correction_attaches_to_exact_observation_and_replays(self):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            decision = record_expense_journal_decision(writer, self.actor, self.a, self.org, journal,
                                                       snapshot_sha256=digest, decision="changes_requested")
        barrier = Barrier(2)

        def record():
            with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
                barrier.wait(timeout=5)
                return record_expense_journal_correction(writer, self.actor, self.a, self.org, journal,
                                                         snapshot_sha256=digest, reason="source_evidence")

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual((first.journal_id, first.snapshot_sha256, first.reviewer_id, first.reason),
                         (journal, digest, self.actor.user_id, "source_evidence"))
        with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalCorrectionConflict):
                record_expense_journal_correction(writer, self.actor, self.a, self.org, journal,
                                                  snapshot_sha256=digest, reason="amount")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_correction_requests")
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, journal), review)
        with psycopg.connect(self.decision_reader_dsn, autocommit=True) as reader:
            page = read_expense_journal_decisions(reader, self.actor, self.a, self.org, journal, snapshot_sha256=digest)
            self.assertEqual(page.decisions, (decision,))
            self.assertEqual(page.corrections, (first,))

    def test_journal_correction_denies_wrong_observation_scope_and_stale_snapshot(self):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        observed = Principal("fictional-observer", self.a, "editor")
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            for actor, decision in ((self.actor, "changes_requested"), (observed, "reviewed")):
                record_expense_journal_decision(writer, actor, self.a, self.org, journal,
                                                snapshot_sha256=digest, decision=decision)
            with self.assertRaises(PermissionError):
                record_expense_journal_correction(writer, self.actor, self.a, self.org, journal,
                                                  snapshot_sha256=digest, reason="amount")
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute("""INSERT INTO omnixat.expense_journal_correction_requests
                (tenant_id,organisation_id,journal_id,snapshot_sha256,reviewer_id,reason)
                VALUES (%s,%s,%s,%s,%s,'amount')""",
                               (self.a, self.org, journal, bytes.fromhex(digest), observed.user_id))

        with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
            def correct(actor=self.actor, tenant=self.a, org=self.org, expected=digest, reason="amount"):
                return record_expense_journal_correction(writer, actor, tenant, org, journal,
                                                         snapshot_sha256=expected, reason=reason)

            for actor, tenant, org, expected in (
                (observed, self.a, self.org, digest),
                (Principal("fictional-no-decision", self.a, "editor"), self.a, self.org, digest),
                (self.other, self.b, self.org, digest),
                (self.actor, self.a, uuid4(), digest),
                (self.actor, self.a, self.org, "0" * 64),
            ):
                with self.subTest(tenant=tenant, org=org, actor=actor.user_id), self.assertRaises(EvidenceNotEligible):
                    correct(actor, tenant, org, expected)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    correct(actor)
            with self.assertRaises(ValueError):
                correct(reason="other")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                correct()
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_correction_requests WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))

    def journal_clarification_fixture(self, *, reason="source_evidence"):
        review = self.journal_decision_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            record_expense_journal_decision(writer, self.actor, self.a, self.org, journal,
                                            snapshot_sha256=digest, decision="changes_requested")
        with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
            record_expense_journal_correction(writer, self.actor, self.a, self.org, journal,
                                              snapshot_sha256=digest, reason=reason)
        return review

    def test_journal_clarification_concurrent_retry_and_conflicts(self):
        review = self.journal_clarification_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        respondent = Principal("fictional-respondent", self.a, "editor")
        answer = "See the fictional invoice, line two."
        kwargs = dict(snapshot_sha256=digest, correction_reviewer_id=self.actor.user_id,
                      reason="source_evidence", answer=answer)
        barrier = Barrier(2)

        def record():
            with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
                barrier.wait(timeout=5)
                return record_expense_journal_clarification(writer, respondent, self.a, self.org, journal, **kwargs)

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual((first.journal_id, first.snapshot_sha256, first.reason,
                          first.correction_reviewer_id, first.answered_by),
                         (journal, digest, "source_evidence", self.actor.user_id, respondent.user_id))
        self.assertEqual(self.owner.execute("""
            SELECT answer, answered_at FROM omnixat.expense_journal_clarification_answers
            WHERE tenant_id=%s AND journal_id=%s
        """, (self.a, journal)).fetchall(), [(answer, first.answered_at)])
        with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalClarificationConflict):
                record_expense_journal_clarification(writer, respondent, self.a, self.org, journal,
                                                     **dict(kwargs, answer="A different fictional invoice."))
            with self.assertRaises(ExpenseJournalClarificationConflict):
                record_expense_journal_clarification(writer, self.actor, self.a, self.org, journal, **kwargs)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_clarification_answers")
            with self.assertRaises(PermissionError):
                read_expense_journal_draft(writer, respondent, self.a, self.org, journal)
        second_reviewer = Principal("fictional-second-reviewer", self.a, "editor")
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            record_expense_journal_decision(writer, second_reviewer, self.a, self.org, journal,
                                            snapshot_sha256=digest, decision="changes_requested")
        with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
            record_expense_journal_correction(writer, second_reviewer, self.a, self.org, journal,
                                              snapshot_sha256=digest, reason="source_evidence")
        with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
            self.assertEqual(record_expense_journal_clarification(
                writer, respondent, self.a, self.org, journal,
                **dict(kwargs, correction_reviewer_id=second_reviewer.user_id),
            ), first)
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, journal), review)
        self.set_active_policy("fictional-v2")
        with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
            with self.assertRaises(EvidenceNotEligible):
                record_expense_journal_clarification(writer, respondent, self.a, self.org, journal, **kwargs)

    def test_journal_review_shares_one_answer_across_corrections_for_the_same_reason(self):
        review = self.journal_clarification_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        second = Principal("fictional-other-reviewer", self.a, "editor")
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.decision_writer_dsn, autocommit=True) as writer:
            record_expense_journal_decision(writer, second, self.a, self.org, journal,
                                            snapshot_sha256=digest, decision="changes_requested")
        with psycopg.connect(self.correction_dsn, autocommit=True) as writer:
            record_expense_journal_correction(writer, second, self.a, self.org, journal,
                                              snapshot_sha256=digest, reason="source_evidence")
        answer = "See the fictional receipt."
        with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
            receipt = record_expense_journal_clarification(
                writer, self.actor, self.a, self.org, journal, snapshot_sha256=digest,
                correction_reviewer_id=second.user_id, reason="source_evidence", answer=answer,
            )
            with self.assertRaises(PermissionError):
                read_expense_journal_decisions(writer, self.actor, self.a, self.org, journal, snapshot_sha256=digest)

        with psycopg.connect(self.decision_reader_dsn, autocommit=True) as reader:
            def page(page_size, cursor=None):
                return read_expense_journal_decisions(reader, viewer, self.a, self.org, journal,
                                                      snapshot_sha256=digest, page_size=page_size, after_reviewer=cursor)

            together = page(2)
            self.assertEqual(len(together.corrections), 2)
            first_page = page(1)
            second_page = page(1, first_page.next_after_reviewer)
            for result in (together, first_page, second_page):
                self.assertEqual(result.answers, (ExpenseJournalClarification(receipt, answer),))
                self.assertEqual(result.follow_up_questions, ())
                self.assertNotIn(answer, repr(result))

    def test_journal_clarification_requires_current_scoped_correction_and_human_editor(self):
        review = self.journal_clarification_fixture()
        journal, digest = review.receipt.id, review.snapshot_sha256
        kwargs = dict(snapshot_sha256=digest, correction_reviewer_id=self.actor.user_id,
                      reason="source_evidence", answer="See the fictional invoice.")
        with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
            for overrides in (
                {"snapshot_sha256": "0" * 64}, {"reason": "account"},
                {"correction_reviewer_id": "fictional-missing-reviewer"},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    record_expense_journal_clarification(writer, self.actor, self.a, self.org, journal,
                                                         **(kwargs | overrides))
            for actor, tenant, organisation in ((self.other, self.b, self.org), (self.actor, self.a, uuid4())):
                with self.subTest(tenant=tenant, organisation=organisation), self.assertRaises(EvidenceNotEligible):
                    record_expense_journal_clarification(writer, actor, tenant, organisation, journal, **kwargs)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    record_expense_journal_clarification(writer, actor, self.a, self.org, journal, **kwargs)
            for answer in ("", " ", "a" * 1001, "first\nsecond", "first\0second"):
                with self.subTest(answer_length=len(answer)), self.assertRaises(ValueError):
                    record_expense_journal_clarification(writer, self.actor, self.a, self.org, journal,
                                                         **dict(kwargs, answer=answer))
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                record_expense_journal_clarification(writer, self.actor, self.a, self.org, journal, **kwargs)
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_clarification_answers WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))


    def record_supporting_answer(self, review, *, reason="source_evidence"):
        with psycopg.connect(self.clarification_dsn, autocommit=True) as writer:
            return record_expense_journal_clarification(
                writer, self.actor, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
                correction_reviewer_id=self.actor.user_id, reason=reason, answer="See the fictional record.",
            )

    def stage_supporting_original(self, original, organisation):
        registration = register_evidence(
            self.runtime, self.actor, self.a, organisation,
            content_sha256=sha256(original).hexdigest(), media_type=self.media_type, byte_size=len(original),
        )
        with TemporaryDirectory() as directory, stage_evidence(
            BytesIO(original), media_type=self.media_type, quarantine_dir=Path(directory),
        ) as staged:
            store_quarantined_evidence(self.runtime, self.actor, self.a, organisation, registration.id, staged)
        return registration

    def test_journal_evidence_link_replays_concurrently_and_preserves_original_answer(self):
        review = self.journal_clarification_fixture()
        answer = self.record_supporting_answer(review)
        supporting = self.stage_supporting_original(b"Fictional,Supporting\r\nInvoice,12\r\n", self.org)
        self.run_scan(lambda *_: "clean", evidence=supporting.id)
        linker = Principal("fictional-evidence-linker", self.a, "editor")
        barrier = Barrier(2)

        def record():
            with psycopg.connect(self.evidence_link_dsn, autocommit=True) as writer:
                barrier.wait(timeout=5)
                return link_expense_journal_clarification_evidence(
                    writer, linker, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
                    reason="source_evidence", evidence_id=supporting.id,
                )

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, retry = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(first, retry)
        self.assertEqual((first.evidence_id, first.linked_by, first.content_sha256, first.scan_policy_version),
                         (supporting.id, linker.user_id, supporting.content_sha256, "fictional-v1"))
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.decision_reader_dsn, autocommit=True) as reader:
            page = read_expense_journal_decisions(
                reader, viewer, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
            )
            self.assertEqual(page.answers[0].supporting_evidence, ExpenseJournalSupportingEvidence(first, True))
        with psycopg.connect(self.evidence_link_dsn, autocommit=True) as writer:
            for actor, candidate in ((self.actor, supporting.id), (linker, self.registration.id)):
                with self.assertRaises(ExpenseJournalEvidenceLinkConflict):
                    link_expense_journal_clarification_evidence(
                        writer, actor, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
                        reason="source_evidence", evidence_id=candidate,
                    )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_clarification_evidence")
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                link_expense_journal_clarification_evidence(
                    writer, linker, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
                    reason="source_evidence", evidence_id=supporting.id,
                )
        with psycopg.connect(self.decision_reader_dsn, autocommit=True) as reader:
            page = read_expense_journal_decisions(
                reader, viewer, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
            )
            self.assertEqual(page.answers[0].supporting_evidence, ExpenseJournalSupportingEvidence(first, False))
            self.assertEqual(page.answers[0].receipt, answer)
            self.assertEqual(page.follow_up_questions, ())
        self.assertEqual(self.record_supporting_answer(review), answer)
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, review.receipt.id), review)

    def test_journal_evidence_link_requires_answer_current_policy_and_scoped_clean_original(self):
        review = self.journal_clarification_fixture()
        with psycopg.connect(self.evidence_link_dsn, autocommit=True) as writer:
            def link(*, actor=self.actor, tenant=self.a, evidence=self.registration.id,
                     digest=review.snapshot_sha256, reason="source_evidence"):
                return link_expense_journal_clarification_evidence(
                    writer, actor, tenant, self.org, review.receipt.id, snapshot_sha256=digest,
                    reason=reason, evidence_id=evidence,
                )

            with self.assertRaises(EvidenceNotEligible):
                link()
            self.record_supporting_answer(review)
            unscanned = self.stage_supporting_original(b"Fictional,Unscanned\r\n", self.org)
            blocked = self.stage_supporting_original(b"Fictional,Blocked\r\n", self.org)
            self.run_scan(lambda *_: "blocked", evidence=blocked.id)
            with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
                other_org = records.create_organisation("Other fictional organisation")["id"]
            outside = self.stage_supporting_original(b"Fictional,Outside\r\n", other_org)
            self.run_scan(lambda *_: "clean", org=other_org, evidence=outside.id)
            for candidate in (unscanned.id, blocked.id, outside.id, uuid4()):
                with self.subTest(evidence=candidate), self.assertRaises(EvidenceNotEligible):
                    link(evidence=candidate)
            for overrides in ({"actor": self.other, "tenant": self.b}, {"digest": "0" * 64}, {"reason": "funding"}):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    link(**overrides)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    link(actor=actor)
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                link()
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_clarification_evidence WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))


    def journal_amount_preview_fixture(self):
        review = self.journal_clarification_fixture(reason="amount")
        self.record_supporting_answer(review, reason="amount")
        original = b"Fictional,Amount\r\nInvoice,15.6700,12.345,0,\r\n"
        supporting = self.stage_supporting_original(original, self.org)
        self.run_scan(lambda *_: "clean", evidence=supporting.id)
        cells = (
            AmountCell("amount", 2, 2), AmountCell("fractional", 2, 3),
            AmountCell("zero", 2, 4), AmountCell("blank", 2, 5),
        )
        job, unrelated_job = uuid4(), uuid4()
        with self.gate_connection() as gate:
            extracted = extract_csv_amounts(gate, self.a, self.org, supporting.id, cells)
            _store_csv_extraction(gate, self.a, self.org, job, extracted)
            unrelated = extract_csv_amounts(gate, self.a, self.org, self.registration.id, cells[:1])
            _store_csv_extraction(gate, self.a, self.org, unrelated_job, unrelated)
        with psycopg.connect(self.evidence_link_dsn, autocommit=True) as writer:
            link_expense_journal_clarification_evidence(
                writer, self.actor, self.a, self.org, review.receipt.id,
                snapshot_sha256=review.snapshot_sha256, reason="amount", evidence_id=supporting.id,
            )
        return review, supporting, job, unrelated_job, cells

    def test_journal_amount_correction_preview_derives_balanced_exact_pence_without_writing(self):
        review, supporting, job, _, cells = self.journal_amount_preview_fixture()
        with psycopg.connect(self.amount_preview_dsn, autocommit=True) as reader:
            preview = preview_expense_journal_amount_correction(
                reader, self.actor, self.a, self.org, review.receipt.id,
                snapshot_sha256=review.snapshot_sha256, extraction_job_id=job, cell=cells[0], currency="GBP",
            )
            self.assertEqual((preview.journal_id, preview.snapshot_sha256, preview.previous_pence, preview.currency),
                             (review.receipt.id, review.snapshot_sha256, 1234, "GBP"))
            self.assertEqual((preview.evidence_id, preview.extraction_job_id, preview.source_cell,
                              preview.content_sha256, preview.scan_policy_version),
                             (supporting.id, job, cells[0], supporting.content_sha256, "fictional-v1"))
            self.assertEqual([(line.account_id, line.side, line.amount_pence) for line in preview.proposed_lines],
                             [(line.account_id, line.side, 1567) for line in review.journal.lines])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)",
                               (self.org, supporting.id))
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, review.receipt.id), review)

    def test_journal_amount_correction_preview_rechecks_exact_cell_link_and_permissions(self):
        review, supporting, job, unrelated_job, cells = self.journal_amount_preview_fixture()
        with psycopg.connect(self.amount_preview_dsn, autocommit=True) as reader:
            def preview(*, actor=self.actor, tenant=self.a, org=self.org, extraction=job,
                        cell=cells[0], digest=review.snapshot_sha256, currency="GBP", connection=reader):
                return preview_expense_journal_amount_correction(
                    connection, actor, tenant, org, review.receipt.id,
                    snapshot_sha256=digest, extraction_job_id=extraction, cell=cell, currency=currency,
                )

            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"digest": "0" * 64},
                {"extraction": unrelated_job}, {"cell": AmountCell("amount", 2, 3)}, {"cell": cells[3]},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    preview(**overrides)
            for overrides in ({"currency": "USD"}, {"cell": cells[1]}, {"cell": cells[2]}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    preview(**overrides)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    preview(actor=actor)
            with psycopg.connect(self.decision_reader_dsn, autocommit=True) as other_reader:
                with self.assertRaises(PermissionError):
                    preview(connection=other_reader)
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                preview()


    def test_amount_correction_proposal_persists_exact_source_and_replays_concurrently(self):
        review, supporting, job, _, cells = self.journal_amount_preview_fixture()
        kwargs = dict(snapshot_sha256=review.snapshot_sha256, extraction_job_id=job, cell=cells[0], currency="GBP")
        start = Barrier(2)

        def create():
            with psycopg.connect(self.amount_proposal_dsn, autocommit=True) as writer:
                start.wait(timeout=5)
                return create_expense_journal_amount_correction(
                    writer, self.actor, self.a, self.org, review.receipt.id, **kwargs,
                )
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: create(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.owner.execute("""
            SELECT id,evidence_id,job_id,field_name,source_row,source_column,content_sha256,
                   scan_policy_version,previous_pence,proposed_pence,expense_account_id,counterpart_account_id,
                   currency,created_by,created_at
            FROM omnixat.expense_journal_amount_corrections WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [
            (first.id, supporting.id, job, cells[0].field_name, cells[0].row, cells[0].column,
             bytes.fromhex(supporting.content_sha256), "fictional-v1", 1234, 1567,
             review.journal.lines[0].account_id, review.journal.lines[1].account_id,
             "GBP", self.actor.user_id, first.created_at),
        ])
        with psycopg.connect(self.amount_proposal_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalAmountCorrectionConflict):
                create_expense_journal_amount_correction(
                    writer, Principal("fictional-other-author", self.a, "editor"), self.a, self.org,
                    review.receipt.id, **kwargs,
                )
            replacement_job = uuid4()
            with self.gate_connection() as gate:
                extracted = extract_csv_amounts(gate, self.a, self.org, supporting.id, cells)
                _store_csv_extraction(gate, self.a, self.org, replacement_job, extracted)
            with self.assertRaises(ExpenseJournalAmountCorrectionConflict):
                create_expense_journal_amount_correction(
                    writer, self.actor, self.a, self.org, review.receipt.id,
                    **dict(kwargs, extraction_job_id=replacement_job),
                )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_amount_corrections")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                create_expense_journal_amount_correction(writer, self.actor, self.a, self.org, review.receipt.id, **kwargs)
        self.set_active_policy("fictional-v1")
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, review.receipt.id), review)

    def test_amount_correction_proposal_rejects_ineligible_source_and_nonhuman_writers(self):
        review, _, job, unrelated_job, cells = self.journal_amount_preview_fixture()
        with psycopg.connect(self.amount_proposal_dsn, autocommit=True) as writer:
            def create(*, actor=self.actor, tenant=self.a, org=self.org, extraction=job,
                       cell=cells[0], digest=review.snapshot_sha256, currency="GBP", connection=writer):
                return create_expense_journal_amount_correction(
                    connection, actor, tenant, org, review.receipt.id, snapshot_sha256=digest,
                    extraction_job_id=extraction, cell=cell, currency=currency,
                )
            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"digest": "0" * 64},
                {"extraction": unrelated_job}, {"cell": cells[3]},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    create(**overrides)
            for overrides in ({"currency": "USD"}, {"cell": cells[1]}, {"cell": cells[2]}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    create(**overrides)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    create(actor=actor)
            with psycopg.connect(self.amount_preview_dsn, autocommit=True) as reader:
                with self.assertRaises(PermissionError):
                    create(connection=reader)
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_amount_corrections WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))

    def test_amount_correction_proposal_holds_eligibility_and_rolls_back(self):
        review, supporting, job, _, cells = self.journal_amount_preview_fixture()
        changes = (
            ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'", ()),
            ("UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s", (self.a,)),
            ("UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE tenant_id=%s", (self.a,)),
            ("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed' WHERE tenant_id=%s", (self.a,)),
            ("UPDATE omnixat.csv_extraction_results SET extractor_version='fictional-changed' WHERE tenant_id=%s AND job_id=%s",
             (self.a, job)),
        )
        with psycopg.connect(self.amount_proposal_dsn, autocommit=True) as writer:
            with self.assertRaisesRegex(RuntimeError, "fictional rollback"), writer.transaction():
                writer.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
                self.assertEqual(writer.execute("""
                    SELECT outcome FROM omnixat_extraction.create_expense_journal_amount_correction
                    (%s,%s,%s,%s,%s,%s,%s,'GBP',%s)
                """, (self.org, review.receipt.id, bytes.fromhex(review.snapshot_sha256), job,
                      cells[0].field_name, cells[0].row, cells[0].column, self.actor.user_id)).fetchone(), ("stored",))
                for statement, args in changes:
                    with self.subTest(statement=statement), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='30ms'")
                            self.owner.execute(statement, args)
                for evidence in (self.registration.id, supporting.id):
                    with self.subTest(evidence=evidence), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='30ms'")
                            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                                FROM omnixat.evidence_scan_verdicts
                                WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
                            """, (self.a, evidence))
                raise RuntimeError("fictional rollback")
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_amount_corrections WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))


    def saved_amount_correction_fixture(self):
        review, supporting, job, _, cells = self.journal_amount_preview_fixture()
        with psycopg.connect(self.amount_proposal_dsn, autocommit=True) as writer:
            receipt = create_expense_journal_amount_correction(
                writer, self.actor, self.a, self.org, review.receipt.id, snapshot_sha256=review.snapshot_sha256,
                extraction_job_id=job, cell=cells[0], currency="GBP",
            )
        return review, supporting, job, cells[0], receipt

    def test_saved_amount_correction_review_returns_exact_attributed_proposal(self):
        journal, supporting, job, cell, receipt = self.saved_amount_correction_fixture()
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.amount_preview_dsn, autocommit=True) as preview:
            expected = preview_expense_journal_amount_correction(
                preview, self.actor, self.a, self.org, journal.receipt.id,
                snapshot_sha256=journal.snapshot_sha256, extraction_job_id=job, cell=cell, currency="GBP",
            )
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            result = read_expense_journal_amount_correction(reader, viewer, self.a, self.org, receipt.id)
            self.assertEqual((result.receipt, result.created_by, result.proposal),
                             (receipt, self.actor.user_id, expected))
            reader.execute("SET TIME ZONE 'Pacific/Auckland'")
            self.assertEqual(read_expense_journal_amount_correction(
                reader, viewer, self.a, self.org, receipt.id,
            ).proposal_sha256, result.proposal_sha256)
            for query, args in (
                ("SELECT * FROM omnixat.expense_journal_amount_corrections", ()),
                ("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)", (self.org, supporting.id)),
            ):
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    reader.execute(query, args)
            with self.assertRaises(PermissionError):
                create_expense_journal_amount_correction(
                    reader, self.actor, self.a, self.org, journal.receipt.id, snapshot_sha256=journal.snapshot_sha256,
                    extraction_job_id=job, cell=cell, currency="GBP",
                )
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as fresh:
            self.assertEqual(read_expense_journal_amount_correction(fresh, viewer, self.a, self.org, receipt.id), result)

    def test_saved_amount_correction_review_rejects_wrong_scope_stale_inputs_and_changed_proposal(self):
        journal, supporting, job, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            def review(actor=self.actor, tenant=self.a, org=self.org, proposal=receipt.id, connection=reader):
                return read_expense_journal_amount_correction(connection, actor, tenant, org, proposal)
            for actor, tenant, org, proposal in (
                (self.other, self.b, self.org, receipt.id),
                (self.actor, self.a, uuid4(), receipt.id),
                (self.actor, self.a, self.org, uuid4()),
            ):
                with self.subTest(tenant=tenant, org=org, proposal=proposal), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Journal correction proposal is unavailable$",
                ):
                    review(actor, tenant, org, proposal)
            for actor in (
                Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    review(actor)
            with psycopg.connect(self.amount_proposal_dsn, autocommit=True) as writer:
                with self.assertRaises(PermissionError):
                    review(connection=writer)

            for field, changed in (
                ("proposed_pence", 999), ("previous_pence", 999),
                ("expense_account_id", uuid4()), ("source_column", 3), ("scan_policy_version", "fictional-old"),
            ):
                select = sql.SQL("SELECT {} FROM omnixat.expense_journal_amount_corrections WHERE tenant_id=%s AND id=%s")
                update = sql.SQL("UPDATE omnixat.expense_journal_amount_corrections SET {}=%s WHERE tenant_id=%s AND id=%s")
                original = self.owner.execute(select.format(sql.Identifier(field)), (self.a, receipt.id)).fetchone()[0]
                self.owner.execute(update.format(sql.Identifier(field)), (changed, self.a, receipt.id))
                with self.subTest(field=field), self.assertRaises(EvidenceNotEligible):
                    review()
                self.owner.execute(update.format(sql.Identifier(field)), (original, self.a, receipt.id))
            self.owner.execute("UPDATE omnixat.csv_extraction_results SET extractor_version='fictional-changed' WHERE job_id=%s",
                               (job,))
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.owner.execute("UPDATE omnixat.csv_extraction_results SET extractor_version='csv-amount-v1' WHERE job_id=%s",
                               (job,))
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.owner.execute("DELETE FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='blocked'",
                               (self.a, supporting.id))
            self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed' WHERE tenant_id=%s AND id=%s",
                               (self.a, journal.receipt.id))
            with self.assertRaises(EvidenceNotEligible):
                review()


    def test_correction_proposal_decision_is_attributed_snapshot_bound_and_retry_safe(self):
        _, _, _, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            review = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
        start = Barrier(2)

        def record():
            with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
                start.wait(timeout=5)
                return record_expense_journal_amount_correction_decision(
                    writer, self.actor, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="reviewed",
                )
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual((first.proposal_id, first.proposal_sha256, first.reviewer_id, first.decision),
                         (receipt.id, review.proposal_sha256, self.actor.user_id, "reviewed"))
        with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalAmountCorrectionDecisionConflict):
                record_expense_journal_amount_correction_decision(
                    writer, self.actor, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="changes_requested",
                )
            self.owner.execute("UPDATE omnixat.expense_journal_amount_corrections SET created_by='fictional-new-author' WHERE id=%s",
                               (receipt.id,))
            with self.assertRaises(EvidenceNotEligible):
                record_expense_journal_amount_correction_decision(
                    writer, self.actor, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="reviewed",
                )
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            changed = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
        self.assertNotEqual(changed.proposal_sha256, review.proposal_sha256)
        with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
            latest = record_expense_journal_amount_correction_decision(
                writer, self.actor, self.a, self.org, receipt.id,
                proposal_sha256=changed.proposal_sha256, decision="changes_requested",
            )
        self.assertEqual(self.owner.execute("""
            SELECT proposal_sha256,decision FROM omnixat.expense_journal_amount_correction_decisions
            WHERE tenant_id=%s AND proposal_id=%s ORDER BY recorded_at
        """, (self.a, receipt.id)).fetchall(), [
            (bytes.fromhex(first.proposal_sha256), "reviewed"),
            (bytes.fromhex(latest.proposal_sha256), "changes_requested"),
        ])

    def test_correction_proposal_decision_rejects_stale_scope_and_nonhuman_review(self):
        _, supporting, _, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            review = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
            with self.assertRaises(PermissionError):
                record_expense_journal_amount_correction_decision(
                    reader, self.actor, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="reviewed",
                )
        with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
            def record(*, actor=self.actor, tenant=self.a, org=self.org, proposal=receipt.id,
                       digest=review.proposal_sha256, decision="reviewed"):
                return record_expense_journal_amount_correction_decision(
                    writer, actor, tenant, org, proposal, proposal_sha256=digest, decision=decision,
                )
            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"proposal": uuid4()}, {"digest": "0" * 64},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    record(**overrides)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    record(actor=actor)
            for overrides in ({"decision": "approved"}, {"digest": "invalid"}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    record(**overrides)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_amount_correction_decisions")
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                record()
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_amount_correction_decisions WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))


    def test_proposal_decision_history_pages_only_the_current_digest(self):
        _, _, _, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            review = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
        viewer = Principal("fictional-viewer", self.a, "viewer")
        earlier = Principal("fictional-reviewer-a", self.a, "editor")
        later = Principal("fictional-reviewer-z", self.a, "editor")
        with psycopg.connect(self.proposal_history_dsn, autocommit=True) as history:
            def page(cursor=None):
                return read_expense_journal_amount_correction_decisions(
                    history, viewer, self.a, self.org, receipt.id, proposal_sha256=review.proposal_sha256,
                    page_size=1, after_reviewer=cursor,
                )
            empty = page()
            self.assertEqual((empty.decisions, empty.next_after_reviewer), ((), None))
            with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
                later_receipt = record_expense_journal_amount_correction_decision(
                    writer, later, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="changes_requested",
                )
                earlier_receipt = record_expense_journal_amount_correction_decision(
                    writer, earlier, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="reviewed",
                )
            self.owner.execute("""INSERT INTO omnixat.expense_journal_amount_correction_decisions
                (tenant_id,organisation_id,proposal_id,proposal_sha256,reviewer_id,decision)
                VALUES (%s,%s,%s,%s,%s,'changes_requested')
            """, (self.a, self.org, receipt.id, sha256(b"fictional old proposal").digest(), earlier.user_id))
            first_page = page()
            self.assertEqual((first_page.decisions, first_page.next_after_reviewer), ((earlier_receipt,), earlier.user_id))
            second_page = page(first_page.next_after_reviewer)
            self.assertEqual((second_page.decisions, second_page.next_after_reviewer), ((later_receipt,), None))
            self.assertEqual(page(later.user_id).decisions, ())
            self.owner.execute("UPDATE omnixat.expense_journal_amount_corrections SET created_by='fictional-new-author' WHERE id=%s",
                               (receipt.id,))
            with self.assertRaises(EvidenceNotEligible):
                page(first_page.next_after_reviewer)

    def test_proposal_decision_history_rejects_wrong_scope_grants_and_stale_sources(self):
        _, supporting, _, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            review = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
            with self.assertRaises(PermissionError):
                read_expense_journal_amount_correction_decisions(
                    reader, self.actor, self.a, self.org, receipt.id, proposal_sha256=review.proposal_sha256,
                )
        with psycopg.connect(self.proposal_history_dsn, autocommit=True) as history:
            def page(*, actor=self.actor, tenant=self.a, org=self.org, proposal=receipt.id,
                     digest=review.proposal_sha256, size=25, cursor=None):
                return read_expense_journal_amount_correction_decisions(
                    history, actor, tenant, org, proposal, proposal_sha256=digest,
                    page_size=size, after_reviewer=cursor,
                )
            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"proposal": uuid4()}, {"digest": "0" * 64},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    page(**overrides)
            for actor in (
                Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    page(actor=actor)
            for overrides in ({"size": 0}, {"size": 101}, {"size": True}, {"cursor": ""}, {"cursor": "x" * 201},
                              {"digest": "invalid"}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    page(**overrides)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                history.execute("SELECT * FROM omnixat.expense_journal_amount_correction_decisions")
            with self.assertRaises(PermissionError):
                record_expense_journal_amount_correction_decision(
                    history, self.actor, self.a, self.org, receipt.id,
                    proposal_sha256=review.proposal_sha256, decision="reviewed",
                )
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                page()


    def test_replacement_preview_preserves_context_and_selects_exact_reviewed_observation(self):
        journal, _, _, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            correction = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
        reviewer = Principal("fictional-selected-reviewer", self.a, "editor")
        with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
            observed = record_expense_journal_amount_correction_decision(
                writer, reviewer, self.a, self.org, receipt.id,
                proposal_sha256=correction.proposal_sha256, decision="reviewed",
            )
        with psycopg.connect(self.replacement_preview_dsn, autocommit=True) as reader:
            result = preview_expense_journal_replacement(
                reader, self.actor, self.a, self.org, receipt.id,
                proposal_sha256=correction.proposal_sha256, reviewer_id=reviewer.user_id,
            )
            self.assertEqual(result.correction, correction)
            self.assertEqual((result.reviewer_id, result.reviewed_at), (reviewer.user_id, observed.recorded_at))
            self.assertEqual((result.accounting_date, result.period_id, result.funding_source_id),
                             (journal.journal.accounting_date, journal.journal.period_id, journal.journal.funding_source_id))
            self.assertEqual([(line.side, line.amount_pence) for line in result.correction.proposal.proposed_lines],
                             [("debit", 1567), ("credit", 1567)])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reader.execute("SELECT * FROM omnixat.expense_journal_amount_correction_decisions")
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, journal.receipt.id), journal)

    def test_replacement_preview_requires_exact_reviewed_decision_scope_and_current_source(self):
        _, supporting, _, _, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            correction = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
        reviewer = Principal("fictional-selected-reviewer", self.a, "editor")
        with psycopg.connect(self.replacement_preview_dsn, autocommit=True) as reader:
            def preview(*, actor=self.actor, tenant=self.a, org=self.org, proposal=receipt.id,
                        digest=correction.proposal_sha256, selected=reviewer.user_id, connection=reader):
                return preview_expense_journal_replacement(
                    connection, actor, tenant, org, proposal, proposal_sha256=digest, reviewer_id=selected,
                )
            with self.assertRaises(EvidenceNotEligible):
                preview()
            with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
                record_expense_journal_amount_correction_decision(
                    writer, self.actor, self.a, self.org, receipt.id,
                    proposal_sha256=correction.proposal_sha256, decision="changes_requested",
                )
                record_expense_journal_amount_correction_decision(
                    writer, reviewer, self.a, self.org, receipt.id,
                    proposal_sha256=correction.proposal_sha256, decision="reviewed",
                )
            self.owner.execute("""INSERT INTO omnixat.expense_journal_amount_correction_decisions
                (tenant_id,organisation_id,proposal_id,proposal_sha256,reviewer_id,decision)
                VALUES (%s,%s,%s,%s,'fictional-historical-reviewer','reviewed')
            """, (self.a, self.org, receipt.id, sha256(b"fictional previous proposal").digest()))
            for overrides in (
                {"selected": self.actor.user_id}, {"selected": "fictional-historical-reviewer"},
                {"selected": "fictional-missing-reviewer"}, {"actor": self.other, "tenant": self.b},
                {"org": uuid4()}, {"proposal": uuid4()}, {"digest": "0" * 64},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    preview(**overrides)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    preview(actor=actor)
            for overrides in ({"selected": ""}, {"selected": "x" * 201}, {"digest": "invalid"}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    preview(**overrides)
            with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as detail_reader:
                with self.assertRaises(PermissionError):
                    preview(connection=detail_reader)
            self.owner.execute("UPDATE omnixat.expense_journal_amount_corrections SET created_by='fictional-changed' WHERE id=%s",
                               (receipt.id,))
            with self.assertRaises(EvidenceNotEligible):
                preview()
            self.owner.execute("UPDATE omnixat.expense_journal_amount_corrections SET created_by=%s WHERE id=%s",
                               (self.actor.user_id, receipt.id))
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                preview()


    def reviewed_replacement_fixture(self):
        journal, supporting, job, cell, receipt = self.saved_amount_correction_fixture()
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            correction = read_expense_journal_amount_correction(reader, self.actor, self.a, self.org, receipt.id)
        reviewer = Principal("fictional-replacement-reviewer", self.a, "editor")
        with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as writer:
            decision = record_expense_journal_amount_correction_decision(
                writer, reviewer, self.a, self.org, receipt.id,
                proposal_sha256=correction.proposal_sha256, decision="reviewed",
            )
        return journal, supporting, job, cell, correction, decision

    def test_replacement_write_is_attributed_preserves_originals_and_replays_concurrently(self):
        journal, supporting, job, cell, correction, decision = self.reviewed_replacement_fixture()
        author = Principal("fictional-replacement-author", self.a, "editor")
        kwargs = dict(proposal_sha256=correction.proposal_sha256, reviewer_id=decision.reviewer_id)
        start = Barrier(2)

        def create():
            with psycopg.connect(self.replacement_writer_dsn, autocommit=True) as writer:
                start.wait(timeout=5)
                return create_expense_journal_replacement(
                    writer, author, self.a, self.org, correction.receipt.id, **kwargs,
                )
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: create(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.owner.execute("""
            SELECT id,original_journal_id,original_snapshot_sha256,proposal_id,proposal_sha256,
                   reviewer_id,reviewed_at,accounting_date,period_id,funding_source_id,
                   expense_account_id,counterpart_account_id,amount_pence,currency,evidence_id,
                   job_id,field_name,source_row,source_column,content_sha256,scan_policy_version,created_by,created_at
            FROM omnixat.expense_journal_replacements WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [
            (first.id, journal.receipt.id, bytes.fromhex(journal.snapshot_sha256), correction.receipt.id,
             bytes.fromhex(correction.proposal_sha256), decision.reviewer_id, decision.recorded_at,
             journal.journal.accounting_date, journal.journal.period_id, journal.journal.funding_source_id,
             journal.journal.lines[0].account_id, journal.journal.lines[1].account_id, 1567, "GBP", supporting.id,
             job, cell.field_name, cell.row, cell.column, bytes.fromhex(supporting.content_sha256),
             "fictional-v1", author.user_id, first.created_at),
        ])
        with psycopg.connect(self.replacement_writer_dsn, autocommit=True) as writer:
            with self.assertRaises(ExpenseJournalReplacementConflict):
                create_expense_journal_replacement(writer, self.actor, self.a, self.org, correction.receipt.id, **kwargs)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                writer.execute("SELECT * FROM omnixat.expense_journal_replacements")
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                create_expense_journal_replacement(writer, author, self.a, self.org, correction.receipt.id, **kwargs)
        self.set_active_policy("fictional-v1")
        with psycopg.connect(self.proposal_reader_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_amount_correction(
                reader, self.actor, self.a, self.org, correction.receipt.id,
            ), correction)
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, journal.receipt.id), journal)

    def test_replacement_write_requires_exact_review_scope_and_human_editor(self):
        _, _, _, _, correction, decision = self.reviewed_replacement_fixture()
        with psycopg.connect(self.replacement_writer_dsn, autocommit=True) as writer:
            def create(*, actor=self.actor, tenant=self.a, org=self.org, proposal=correction.receipt.id,
                       digest=correction.proposal_sha256, reviewer=decision.reviewer_id, connection=writer):
                return create_expense_journal_replacement(
                    connection, actor, tenant, org, proposal, proposal_sha256=digest, reviewer_id=reviewer,
                )
            with psycopg.connect(self.proposal_decision_dsn, autocommit=True) as decision_writer:
                record_expense_journal_amount_correction_decision(
                    decision_writer, self.actor, self.a, self.org, correction.receipt.id,
                    proposal_sha256=correction.proposal_sha256, decision="changes_requested",
                )
            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"proposal": uuid4()},
                {"digest": "0" * 64}, {"reviewer": self.actor.user_id}, {"reviewer": "fictional-missing"},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    create(**overrides)
            for actor in (
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("viewer", self.a, "viewer"),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    create(actor=actor)
            with self.assertRaises(ValueError):
                create(reviewer="")
            with psycopg.connect(self.replacement_preview_dsn, autocommit=True) as preview:
                with self.assertRaises(PermissionError):
                    create(connection=preview)
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_replacements WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))

    def test_replacement_write_holds_inputs_through_commit_and_rolls_back(self):
        journal, supporting, job, _, correction, decision = self.reviewed_replacement_fixture()
        changes = (
            ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'", ()),
            ("UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s", (self.a,)),
            ("UPDATE omnixat.expense_journal_amount_corrections SET created_by='fictional-changed' WHERE id=%s",
             (correction.receipt.id,)),
            ("UPDATE omnixat.expense_journal_amount_correction_decisions SET recorded_at=clock_timestamp() WHERE proposal_id=%s",
             (correction.receipt.id,)),
            ("UPDATE omnixat.csv_extraction_results SET extractor_version='fictional-changed' WHERE job_id=%s", (job,)),
            ("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed' WHERE id=%s", (journal.receipt.id,)),
        )
        with psycopg.connect(self.replacement_writer_dsn, autocommit=True) as writer:
            with self.assertRaisesRegex(RuntimeError, "fictional rollback"), writer.transaction():
                writer.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
                self.assertEqual(writer.execute("""
                    SELECT outcome FROM omnixat_extraction.create_expense_journal_replacement(%s,%s,%s,%s,%s)
                """, (self.org, correction.receipt.id, bytes.fromhex(correction.proposal_sha256),
                      decision.reviewer_id, self.actor.user_id)).fetchone(), ("stored",))
                for statement, args in changes:
                    with self.subTest(statement=statement), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='30ms'")
                            self.owner.execute(statement, args)
                for evidence in (self.registration.id, supporting.id):
                    with self.subTest(evidence=evidence), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='30ms'")
                            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                                FROM omnixat.evidence_scan_verdicts
                                WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
                            """, (self.a, evidence))
                raise RuntimeError("fictional rollback")
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_replacements WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))

    def saved_replacement_fixture(self):
        journal, supporting, job, _, correction, decision = self.reviewed_replacement_fixture()
        author = Principal("fictional-replacement-author", self.a, "editor")
        with psycopg.connect(self.replacement_writer_dsn, autocommit=True) as writer:
            receipt = create_expense_journal_replacement(
                writer, author, self.a, self.org, correction.receipt.id,
                proposal_sha256=correction.proposal_sha256, reviewer_id=decision.reviewer_id,
            )
        return journal, supporting, job, correction, decision, author, receipt

    def test_saved_replacement_review_returns_exact_attribution_and_balanced_preview(self):
        _, supporting, _, correction, decision, author, receipt = self.saved_replacement_fixture()
        viewer = Principal("fictional-viewer", self.a, "viewer")
        with psycopg.connect(self.replacement_preview_dsn, autocommit=True) as reader:
            expected = preview_expense_journal_replacement(
                reader, self.actor, self.a, self.org, correction.receipt.id,
                proposal_sha256=correction.proposal_sha256, reviewer_id=decision.reviewer_id,
            )
        with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as reader:
            result = read_expense_journal_replacement(reader, viewer, self.a, self.org, receipt.id)
            self.assertEqual((result.receipt, result.created_by, result.draft), (receipt, author.user_id, expected))
            for query, args in (
                ("SELECT * FROM omnixat.expense_journal_replacements", ()),
                ("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)", (self.org, supporting.id)),
            ):
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    reader.execute(query, args)
            with self.assertRaises(PermissionError):
                create_expense_journal_replacement(
                    reader, self.actor, self.a, self.org, correction.receipt.id,
                    proposal_sha256=correction.proposal_sha256, reviewer_id=decision.reviewer_id,
                )
        with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as fresh:
            self.assertEqual(read_expense_journal_replacement(fresh, viewer, self.a, self.org, receipt.id), result)

    def test_saved_replacement_review_rejects_wrong_scope_changed_context_and_stale_source(self):
        journal, supporting, _, correction, decision, _, receipt = self.saved_replacement_fixture()
        with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as reader:
            def review(*, actor=self.actor, tenant=self.a, org=self.org, replacement=receipt.id, connection=reader):
                return read_expense_journal_replacement(connection, actor, tenant, org, replacement)
            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"replacement": uuid4()},
            ):
                with self.subTest(overrides=overrides), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Saved journal replacement is unavailable$",
                ):
                    review(**overrides)
            for actor in (
                Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    review(actor=actor)
            with psycopg.connect(self.replacement_writer_dsn, autocommit=True) as writer:
                with self.assertRaises(PermissionError):
                    review(connection=writer)

            for field, changed in (
                ("amount_pence", 999), ("accounting_date", date(2026, 11, 7)),
                ("period_id", uuid4()), ("funding_source_id", uuid4()), ("expense_account_id", uuid4()),
                ("source_column", 3), ("scan_policy_version", "fictional-old"),
                ("original_snapshot_sha256", bytes(32)),
            ):
                select = sql.SQL("SELECT {} FROM omnixat.expense_journal_replacements WHERE tenant_id=%s AND id=%s")
                update = sql.SQL("UPDATE omnixat.expense_journal_replacements SET {}=%s WHERE tenant_id=%s AND id=%s")
                original = self.owner.execute(select.format(sql.Identifier(field)), (self.a, receipt.id)).fetchone()[0]
                self.owner.execute(update.format(sql.Identifier(field)), (changed, self.a, receipt.id))
                with self.subTest(field=field), self.assertRaises(EvidenceNotEligible):
                    review()
                self.owner.execute(update.format(sql.Identifier(field)), (original, self.a, receipt.id))
            self.owner.execute("""UPDATE omnixat.expense_journal_amount_correction_decisions
                SET recorded_at=recorded_at + interval '1 second' WHERE tenant_id=%s AND proposal_id=%s AND reviewer_id=%s
            """, (self.a, correction.receipt.id, decision.reviewer_id))
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.owner.execute("""UPDATE omnixat.expense_journal_amount_correction_decisions
                SET recorded_at=%s WHERE tenant_id=%s AND proposal_id=%s AND reviewer_id=%s
            """, (decision.recorded_at, self.a, correction.receipt.id, decision.reviewer_id))
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                review()
            self.owner.execute("DELETE FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='blocked'",
                               (self.a, supporting.id))
            self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed' WHERE tenant_id=%s AND id=%s",
                               (self.a, journal.receipt.id))
            with self.assertRaises(EvidenceNotEligible):
                review()


    def test_replacement_selection_preserves_lineage_and_replays_concurrently(self):
        journal, _, _, correction, _, author, replacement = self.saved_replacement_fixture()
        selector = Principal("fictional-selector", self.a, "editor")
        start = Barrier(2)

        def choose():
            with psycopg.connect(self.replacement_selector_dsn, autocommit=True) as writer:
                start.wait(timeout=5)
                return select_expense_journal_replacement(
                    writer, selector, self.a, self.org, journal.receipt.id, replacement.id,
                    proposal_sha256=correction.proposal_sha256,
                )
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: choose(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual((first.original_journal_id, first.replacement_id, first.original_snapshot_sha256,
                          first.proposal_sha256, first.selected_by),
                         (journal.receipt.id, replacement.id, journal.snapshot_sha256,
                          correction.proposal_sha256, selector.user_id))
        self.assertEqual(self.owner.execute("""
            SELECT original_journal_id,replacement_id,original_snapshot_sha256,proposal_sha256,selected_by,selected_at
            FROM omnixat.expense_journal_replacement_selections WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [(journal.receipt.id, replacement.id, bytes.fromhex(journal.snapshot_sha256),
                                     bytes.fromhex(correction.proposal_sha256), selector.user_id, first.selected_at)])
        with psycopg.connect(self.replacement_selector_dsn, autocommit=True) as fresh:
            self.assertEqual(fresh.execute("""
                SELECT outcome FROM omnixat_extraction.select_expense_journal_replacement(%s,%s,%s,%s,%s)
            """, (self.org, journal.receipt.id, replacement.id, bytes.fromhex(correction.proposal_sha256),
                  selector.user_id)).fetchone(), ("unavailable",))
            self.assertEqual(select_expense_journal_replacement(
                fresh, selector, self.a, self.org, journal.receipt.id, replacement.id,
                proposal_sha256=correction.proposal_sha256,
            ), first)
            with self.assertRaises(ExpenseJournalSelectionConflict):
                select_expense_journal_replacement(
                    fresh, self.actor, self.a, self.org, journal.receipt.id, replacement.id,
                    proposal_sha256=correction.proposal_sha256,
                )
            for query in ("SELECT * FROM omnixat.expense_journal_replacement_selections",
                          "SELECT * FROM omnixat.expense_journal_replacements"):
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    fresh.execute(query)
        for field, changed in (("tenant_id", self.b), ("organisation_id", uuid4()),
                               ("original_journal_id", uuid4()), ("replacement_id", uuid4())):
            with self.subTest(field=field), self.assertRaises(psycopg.errors.ForeignKeyViolation):
                self.owner.execute(sql.SQL(
                    "UPDATE omnixat.expense_journal_replacement_selections SET {}=%s WHERE tenant_id=%s"
                ).format(sql.Identifier(field)), (changed, self.a))
        with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as reader:
            saved = read_expense_journal_replacement(reader, self.actor, self.a, self.org, replacement.id)
            self.assertEqual((saved.receipt, saved.created_by), (replacement, author.user_id))
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, self.actor, self.a, self.org, journal.receipt.id), journal)

    def test_replacement_selection_checks_scope_actor_digest_and_current_eligibility(self):
        journal, supporting, _, correction, _, _, replacement = self.saved_replacement_fixture()
        with psycopg.connect(self.replacement_selector_dsn, autocommit=True) as writer:
            def choose(*, actor=self.actor, tenant=self.a, org=self.org, original=journal.receipt.id,
                       selected=replacement.id, digest=correction.proposal_sha256, connection=writer):
                return select_expense_journal_replacement(
                    connection, actor, tenant, org, original, selected, proposal_sha256=digest,
                )
            for overrides in (
                {"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"original": uuid4()},
                {"selected": uuid4()}, {"digest": "00" * 32},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(EvidenceNotEligible):
                    choose(**overrides)
            for actor in (
                self.other, Principal("viewer", self.a, "viewer"),
                Principal("agent", self.a, "editor", actor_kind="agent"),
                Principal("api", self.a, "editor", api_scopes=frozenset({"records:write", "evidence:read"})),
                Principal("owner", None, staff_role="platform_owner", mfa_verified=True),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    choose(actor=actor)
            for overrides in ({"digest": "bad"}, {"actor": Principal(" ", self.a, "editor")}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    choose(**overrides)
            with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as reader:
                with self.assertRaises(PermissionError):
                    choose(connection=reader)
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                choose()
            self.set_active_policy("fictional-v1")
            self.owner.execute("UPDATE omnixat.expense_journal_replacements SET amount_pence=999 WHERE tenant_id=%s",
                               (self.a,))
            with self.assertRaises(EvidenceNotEligible):
                choose()
            self.owner.execute("UPDATE omnixat.expense_journal_replacements SET amount_pence=%s WHERE tenant_id=%s",
                               (correction.proposal.proposed_lines[0].amount_pence, self.a))
            receipt = choose()
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                choose()
            self.assertEqual(self.owner.execute("""
                SELECT selected_at FROM omnixat.expense_journal_replacement_selections WHERE tenant_id=%s
            """, (self.a,)).fetchall(), [(receipt.selected_at,)])

    def test_replacement_selection_locks_eligibility_through_commit_and_rolls_back(self):
        journal, supporting, job, correction, _, _, replacement = self.saved_replacement_fixture()
        with psycopg.connect(self.replacement_selector_dsn, autocommit=True) as writer:
            with self.assertRaisesRegex(RuntimeError, "fictional rollback"), writer.transaction():
                writer.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (self.a,))
                self.assertEqual(writer.execute("""
                    SELECT outcome FROM omnixat_extraction.select_expense_journal_replacement(%s,%s,%s,%s,%s)
                """, (self.org, journal.receipt.id, replacement.id, bytes.fromhex(correction.proposal_sha256),
                      self.actor.user_id)).fetchone(), ("stored",))
                for statement, args in (
                    ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'", ()),
                    ("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed' WHERE id=%s", (journal.receipt.id,)),
                    ("UPDATE omnixat.expense_journal_replacements SET amount_pence=999 WHERE id=%s", (replacement.id,)),
                    ("UPDATE omnixat.expense_journal_amount_correction_decisions SET recorded_at=clock_timestamp() WHERE proposal_id=%s",
                     (correction.receipt.id,)),
                    ("UPDATE omnixat.csv_extraction_results SET extractor_version='fictional-changed' WHERE job_id=%s", (job,)),
                ):
                    with self.subTest(statement=statement), self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='30ms'")
                            self.owner.execute(statement, args)
                with self.assertRaises(psycopg.errors.LockNotAvailable), self.owner.transaction():
                    self.owner.execute("SET LOCAL lock_timeout='30ms'")
                    self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                        (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                        SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                        FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
                    """, (self.a, supporting.id))
                raise RuntimeError("fictional rollback")
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_replacement_selections WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))
        self.assertEqual(self.owner.execute("""
            SELECT id FROM omnixat.expense_journal_replacements WHERE tenant_id=%s
        """, (self.a,)).fetchall(), [(replacement.id,)])


    def test_current_journal_without_selection_returns_original_and_read_only_lineage(self):
        original = self.journal_decision_fixture()
        viewer = Principal("fictional-current-viewer", self.a, "viewer")
        with psycopg.connect(self.current_journal_reader_dsn, autocommit=True) as reader:
            current = read_current_expense_journal(reader, viewer, self.a, self.org, original.receipt.id)
            self.assertEqual(current.original, original)
            self.assertEqual(current.journal, original.journal)
            self.assertIsNone(current.replacement)
            self.assertIsNone(current.selection)
            self.assertEqual(reader.execute("""
                SELECT * FROM omnixat_extraction.read_current_expense_journal(%s,%s)
            """, (self.org, original.receipt.id)).fetchall(), [])
            for query, args in (
                ("SELECT * FROM omnixat.expense_journal_replacement_selections", ()),
                ("SELECT * FROM omnixat.expense_journal_drafts", ()),
                ("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)",
                 (self.org, original.journal.evidence_id)),
            ):
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    reader.execute(query, args)
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat.expense_journal_replacement_selections WHERE tenant_id=%s
        """, (self.a,)).fetchone(), (0,))

    def test_current_journal_uses_only_explicit_selection_with_exact_balanced_source(self):
        original, _, _, correction, _, _, replacement = self.saved_replacement_fixture()
        viewer = Principal("fictional-current-viewer", self.a, "viewer")
        with psycopg.connect(self.current_journal_reader_dsn, autocommit=True) as reader:
            before = read_current_expense_journal(reader, viewer, self.a, self.org, original.receipt.id)
            self.assertEqual(before.journal, original.journal)
            self.assertIsNone(before.replacement)
            self.assertIsNone(before.selection)
        selector = Principal("fictional-current-selector", self.a, "editor")
        with psycopg.connect(self.replacement_selector_dsn, autocommit=True) as writer:
            selected = select_expense_journal_replacement(
                writer, selector, self.a, self.org, original.receipt.id, replacement.id,
                proposal_sha256=correction.proposal_sha256,
            )
        with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as reader:
            expected = read_expense_journal_replacement(reader, viewer, self.a, self.org, replacement.id)
        with psycopg.connect(self.current_journal_reader_dsn, autocommit=True) as reader:
            current = read_current_expense_journal(reader, viewer, self.a, self.org, original.receipt.id)
            self.assertEqual((current.original, current.replacement, current.selection), (original, expected, selected))
            effective = current.journal
            self.assertEqual(effective.lines, correction.proposal.proposed_lines)
            self.assertEqual((effective.evidence_id, effective.extraction_job_id, effective.source_cell,
                              effective.content_sha256, effective.scan_policy_version),
                             (correction.proposal.evidence_id, correction.proposal.extraction_job_id,
                              correction.proposal.source_cell, correction.proposal.content_sha256,
                              correction.proposal.scan_policy_version))
            self.assertEqual((effective.draft_id, effective.funding_source_id, effective.currency,
                              effective.accounting_date, effective.period_id),
                             (original.journal.draft_id, original.journal.funding_source_id, "GBP",
                              original.journal.accounting_date, original.journal.period_id))
            self.assertNotEqual(effective.lines, original.journal.lines)
            self.assertEqual(sum(line.amount_pence for line in effective.lines if line.side == "debit"),
                             sum(line.amount_pence for line in effective.lines if line.side == "credit"))
            with self.assertRaises(PermissionError):
                select_expense_journal_replacement(
                    reader, selector, self.a, self.org, original.receipt.id, replacement.id,
                    proposal_sha256=correction.proposal_sha256,
                )
        with psycopg.connect(self.current_journal_reader_dsn, autocommit=True) as fresh:
            self.assertEqual(read_current_expense_journal(fresh, viewer, self.a, self.org, original.receipt.id), current)
        with psycopg.connect(self.journal_review_dsn, autocommit=True) as reader:
            self.assertEqual(read_expense_journal_draft(reader, viewer, self.a, self.org, original.receipt.id), original)

    def test_current_journal_rejects_wrong_scope_and_invalid_selected_replacement_without_fallback(self):
        original, supporting, _, correction, decision, _, replacement = self.saved_replacement_fixture()
        with psycopg.connect(self.replacement_selector_dsn, autocommit=True) as writer:
            selected = select_expense_journal_replacement(
                writer, self.actor, self.a, self.org, original.receipt.id, replacement.id,
                proposal_sha256=correction.proposal_sha256,
            )
        with psycopg.connect(self.current_journal_reader_dsn, autocommit=True) as reader:
            def read(*, actor=self.actor, tenant=self.a, org=self.org, journal=original.receipt.id, connection=reader):
                return read_current_expense_journal(connection, actor, tenant, org, journal)
            for overrides in ({"actor": self.other, "tenant": self.b}, {"org": uuid4()}, {"journal": uuid4()}):
                with self.subTest(overrides=overrides), self.assertRaisesRegex(
                    EvidenceNotEligible, "^Current journal draft is unavailable$",
                ):
                    read(**overrides)
            for actor in (
                self.other, Principal("agent", self.a, "viewer", actor_kind="agent"),
                Principal("api", self.a, "viewer", api_scopes=frozenset({"records:read", "evidence:read"})),
                Principal("staff", None, staff_role="platform_owner", mfa_verified=True),
            ):
                with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                    read(actor=actor)
            with psycopg.connect(self.replacement_reader_dsn, autocommit=True) as other_reader:
                with self.assertRaises(PermissionError):
                    read(connection=other_reader)
            for field in ("original_snapshot_sha256", "proposal_sha256"):
                self.owner.execute(sql.SQL(
                    "UPDATE omnixat.expense_journal_replacement_selections SET {}=%s WHERE tenant_id=%s"
                ).format(sql.Identifier(field)), (bytes(32), self.a))
                with self.subTest(field=field), self.assertRaises(EvidenceNotEligible):
                    read()
                self.owner.execute(sql.SQL(
                    "UPDATE omnixat.expense_journal_replacement_selections SET {}=%s WHERE tenant_id=%s"
                ).format(sql.Identifier(field)), (bytes.fromhex(getattr(selected, field)), self.a))
            self.owner.execute("""UPDATE omnixat.expense_journal_amount_correction_decisions
                SET recorded_at=recorded_at + interval '1 second' WHERE tenant_id=%s AND proposal_id=%s AND reviewer_id=%s
            """, (self.a, correction.receipt.id, decision.reviewer_id))
            with self.assertRaises(EvidenceNotEligible):
                read()
            self.owner.execute("""UPDATE omnixat.expense_journal_amount_correction_decisions
                SET recorded_at=%s WHERE tenant_id=%s AND proposal_id=%s AND reviewer_id=%s
            """, (decision.recorded_at, self.a, correction.receipt.id, decision.reviewer_id))
            self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
                (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                SELECT tenant_id,evidence_id,content_sha256,byte_size,policy_version,'blocked'
                FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='clean'
            """, (self.a, supporting.id))
            with self.assertRaises(EvidenceNotEligible):
                read()
            # The original still passes its separate historical read.
            with psycopg.connect(self.journal_review_dsn, autocommit=True) as original_reader:
                self.assertEqual(read_expense_journal_draft(
                    original_reader, self.actor, self.a, self.org, original.receipt.id,
                ), original)
            self.owner.execute("DELETE FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND evidence_id=%s AND verdict='blocked'",
                               (self.a, supporting.id))
            self.set_active_policy("fictional-v2")
            with self.assertRaises(EvidenceNotEligible):
                read()
            self.set_active_policy("fictional-v1")
            self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed' WHERE tenant_id=%s AND id=%s",
                               (self.a, original.receipt.id))
            with self.assertRaises(EvidenceNotEligible):
                read()
