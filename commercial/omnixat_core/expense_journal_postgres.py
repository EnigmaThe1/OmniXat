"""Prepare, save and review two-line expense journal drafts without posting."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_csv import AmountCell
from .evidence_drafts_postgres import _require_draft_role, _validate_cell
from .evidence_extraction_postgres import EvidenceNotEligible
from .evidence_postgres import _authorize
from .expense_context import expense_pence
from .expense_funding_postgres import _TABLES as _FUNDING_TABLES
from .journal_correction_questions import (
    ExpenseJournalFollowUpQuestion, JournalCorrectionReason, journal_correction_questions,
)
from .postgres import _tenant_transaction

_TABLES = (*_FUNDING_TABLES, "expense_counterpart_policy")
_DRAFT_TABLES = (*_TABLES, "expense_journal_drafts")


@dataclass(frozen=True)
class JournalPreviewLine:
    account_id: UUID
    side: Literal["debit", "credit"]
    amount_pence: int = field(repr=False)


@dataclass(frozen=True)
class ExpenseJournalPreview:
    draft_id: UUID
    funding_source_id: UUID
    currency: Literal["GBP"]
    accounting_date: date
    period_id: UUID
    evidence_id: UUID
    extraction_job_id: UUID
    source_cell: AmountCell
    scan_policy_version: str
    content_sha256: str
    lines: tuple[JournalPreviewLine, JournalPreviewLine]


def _journal_scope(actor, tenant_id, organisation_id, draft_id, counterpart_account_id):
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal preparation required")
    if type(counterpart_account_id) is not UUID or not counterpart_account_id.int:
        raise ValueError("Select an explicit counterpart account")
    organisation, draft = (UUID(str(value)) for value in (organisation_id, draft_id))

    return tenant, organisation, draft


def prepare_expense_journal_preview(
    connection, actor, tenant_id, organisation_id, draft_id, *, counterpart_account_id: UUID,
) -> ExpenseJournalPreview:
    """Check the selected counterpart and return two equal, opposing GBP lines."""
    tenant, organisation, draft = _journal_scope(actor, tenant_id, organisation_id, draft_id, counterpart_account_id)

    with _tenant_transaction(connection, tenant, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_preview")
            cursor.execute("SELECT * FROM omnixat_extraction.read_expense_journal_preview(%s,%s,%s)",
                           (organisation, draft, counterpart_account_id))
            row = cursor.fetchone()
    if row is None:
        raise EvidenceNotEligible("Expense draft, funding source or counterpart account is unavailable")
    return _journal_details(row, draft)


def _journal_details(row, draft):
    pence = int(row["amount_pence"])
    return ExpenseJournalPreview(
        draft, row["funding_source_id"], row["currency"], row["accounting_date"], row["period_id"],
        row["evidence_id"], row["job_id"], AmountCell(row["field_name"], row["source_row"], row["source_column"]),
        row["policy_version"], row["content_sha256"].hex(),
        (JournalPreviewLine(row["expense_account_id"], "debit", pence),
         JournalPreviewLine(row["counterpart_account_id"], "credit", pence)),
    )


class ExpenseJournalConflict(Exception):
    """An eligible expense already has a journal draft with different inputs."""


@dataclass(frozen=True)
class ExpenseJournalReceipt:
    id: UUID
    expense_draft_id: UUID
    created_at: datetime


def create_expense_journal_draft(
    connection, actor, tenant_id, organisation_id, draft_id, *, counterpart_account_id: UUID,
) -> ExpenseJournalReceipt:
    """Save the current eligible preview as a draft and return an idempotent receipt."""
    tenant, organisation, draft = _journal_scope(actor, tenant_id, organisation_id, draft_id, counterpart_account_id)
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid journal attribution")
    with _tenant_transaction(connection, tenant, write=True, tables_required=_DRAFT_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "create_expense_journal_draft")
            cursor.execute("SELECT * FROM omnixat_extraction.create_expense_journal_draft(%s,%s,%s,%s)",
                           (organisation, draft, counterpart_account_id, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Expense draft, funding source or counterpart account is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseJournalConflict("A different journal draft already exists for this expense")
        if row["outcome"] != "stored":
            raise RuntimeError("Journal draft receipt unavailable")
        return ExpenseJournalReceipt(row["journal_id"], draft, row["created_at"])


@dataclass(frozen=True)
class ExpenseJournalReview:
    receipt: ExpenseJournalReceipt
    created_by: str = field(repr=False)
    journal: ExpenseJournalPreview
    snapshot_sha256: str


def read_expense_journal_draft(
    connection, actor, tenant_id, organisation_id, journal_id,
) -> ExpenseJournalReview:
    """Review one saved journal only while its snapshot matches eligible inputs."""
    tenant = _authorize(actor, tenant_id, "records:read")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal review required")
    organisation, journal = (UUID(str(value)) for value in (organisation_id, journal_id))
    with _tenant_transaction(connection, tenant, tables_required=_DRAFT_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_review")
            cursor.execute("SELECT * FROM omnixat_extraction.read_expense_journal_review(%s,%s)",
                           (organisation, journal))
            row = cursor.fetchone()
    if row is None:
        raise EvidenceNotEligible("Journal draft is unavailable")
    draft = row["expense_draft_id"]
    receipt = ExpenseJournalReceipt(row["journal_id"], draft, row["journal_created_at"])
    return ExpenseJournalReview(receipt, row["journal_created_by"], _journal_details(row, draft),
                                row["snapshot_sha256"].hex())


JournalDecision = Literal["reviewed", "changes_requested"]


class ExpenseJournalDecisionConflict(Exception):
    """The reviewer already made a different decision for this snapshot."""


@dataclass(frozen=True)
class ExpenseJournalDecisionReceipt:
    journal_id: UUID
    snapshot_sha256: str
    decision: JournalDecision
    reviewer_id: str = field(repr=False)
    recorded_at: datetime


def record_expense_journal_decision(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, decision: JournalDecision,
) -> ExpenseJournalDecisionReceipt:
    """Record a historical bookkeeping observation with no approval or posting authority."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal review required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid journal reviewer")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    if decision not in ("reviewed", "changes_requested"):
        raise ValueError("Unsupported journal review decision")
    organisation, journal = (UUID(str(value)) for value in (organisation_id, journal_id))

    with _tenant_transaction(connection, tenant, write=True,
                             tables_required=(*_DRAFT_TABLES, "expense_journal_review_decisions")):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "record_expense_journal_decision")
            cursor.execute("SELECT * FROM omnixat_extraction.record_expense_journal_decision(%s,%s,%s,%s,%s)",
                           (organisation, journal, bytes.fromhex(snapshot_sha256), decision, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Journal snapshot is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseJournalDecisionConflict("A different decision already exists for this reviewer and snapshot")
        if row["outcome"] != "stored":
            raise RuntimeError("Journal decision receipt unavailable")
        return ExpenseJournalDecisionReceipt(journal, snapshot_sha256, decision, actor_id, row["decision_recorded_at"])


class ExpenseJournalCorrectionConflict(Exception):
    """A different correction reason is already attached to the observation."""


@dataclass(frozen=True)
class ExpenseJournalCorrectionReceipt:
    journal_id: UUID
    snapshot_sha256: str
    reason: JournalCorrectionReason
    reviewer_id: str = field(repr=False)
    recorded_at: datetime


@dataclass(frozen=True)
class ExpenseJournalClarificationReceipt:
    journal_id: UUID
    snapshot_sha256: str
    reason: JournalCorrectionReason
    correction_reviewer_id: str = field(repr=False)
    answered_by: str = field(repr=False)
    answered_at: datetime


@dataclass(frozen=True)
class ExpenseJournalEvidenceLink:
    journal_id: UUID
    snapshot_sha256: str
    reason: JournalCorrectionReason
    evidence_id: UUID
    content_sha256: str = field(repr=False)
    scan_policy_version: str
    linked_by: str = field(repr=False)
    linked_at: datetime


@dataclass(frozen=True)
class ExpenseJournalSupportingEvidence:
    link: ExpenseJournalEvidenceLink
    is_eligible: bool


@dataclass(frozen=True)
class ExpenseJournalClarification:
    receipt: ExpenseJournalClarificationReceipt
    answer: str = field(repr=False)
    supporting_evidence: ExpenseJournalSupportingEvidence | None = None


@dataclass(frozen=True)
class ExpenseJournalDecisionPage:
    decisions: tuple[ExpenseJournalDecisionReceipt, ...]
    next_after_reviewer: str | None = field(repr=False)
    corrections: tuple[ExpenseJournalCorrectionReceipt, ...] = ()
    answers: tuple[ExpenseJournalClarification, ...] = ()

    @property
    def follow_up_questions(self) -> tuple[ExpenseJournalFollowUpQuestion, ...]:
        answered_reasons = {answer.receipt.reason for answer in self.answers}
        return journal_correction_questions(
            correction.reason for correction in self.corrections if correction.reason not in answered_reasons
        )


def read_expense_journal_decisions(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, page_size: int = 25, after_reviewer: str | None = None,
) -> ExpenseJournalDecisionPage:
    """Read observations, answers and supporting evidence for one eligible snapshot."""
    tenant = _authorize(actor, tenant_id, "records:read")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal review required")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("Journal decision page size must be between 1 and 100")
    if after_reviewer is not None and (
        type(after_reviewer) is not str or not after_reviewer.strip()
        or len(after_reviewer) > 200 or "\0" in after_reviewer
    ):
        raise ValueError("Invalid journal decision cursor")
    organisation, journal = (UUID(str(value)) for value in (organisation_id, journal_id))

    with _tenant_transaction(connection, tenant,
                             tables_required=(*_DRAFT_TABLES, "expense_journal_review_decisions",
                                              "expense_journal_correction_requests",
                                              "expense_journal_clarification_answers",
                                              "expense_journal_clarification_evidence")):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_decisions_with_evidence")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.read_expense_journal_decisions_with_evidence(%s,%s,%s,%s,%s)
            """,
                           (organisation, journal, bytes.fromhex(snapshot_sha256), after_reviewer, page_size))
            rows = cursor.fetchall()
    if not rows:
        raise EvidenceNotEligible("Journal snapshot is unavailable")
    if rows[0]["reviewer_id"] is None:
        return ExpenseJournalDecisionPage((), None)
    decisions = tuple(ExpenseJournalDecisionReceipt(
        journal, snapshot_sha256, row["decision"], row["reviewer_id"], row["recorded_at"],
    ) for row in rows[:page_size])
    next_cursor = decisions[-1].reviewer_id if len(rows) > page_size else None
    corrections = tuple(ExpenseJournalCorrectionReceipt(
        journal, snapshot_sha256, row["correction_reason"], row["reviewer_id"], row["correction_recorded_at"],
    ) for row in rows[:page_size] if row["correction_reason"] is not None)
    answer_rows = {row["correction_reason"]: row for row in rows[:page_size] if row["answered_at"] is not None}
    answers = []
    for reason, row in answer_rows.items():
        receipt = ExpenseJournalClarificationReceipt(
            journal, snapshot_sha256, reason, row["answer_reviewer_id"], row["answered_by"], row["answered_at"],
        )
        supporting_evidence = None
        if row["evidence_id"] is not None:
            link = ExpenseJournalEvidenceLink(
                journal, snapshot_sha256, reason, row["evidence_id"], row["evidence_fingerprint"].hex(),
                row["evidence_scan_policy"], row["evidence_linked_by"], row["evidence_linked_at"],
            )
            supporting_evidence = ExpenseJournalSupportingEvidence(link, row["evidence_is_eligible"])
        answers.append(ExpenseJournalClarification(receipt, row["answer"], supporting_evidence))
    return ExpenseJournalDecisionPage(decisions, next_cursor, corrections, tuple(answers))


def record_expense_journal_correction(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, reason: JournalCorrectionReason,
) -> ExpenseJournalCorrectionReceipt:
    """Attach a structured reason to the caller's changes-requested observation."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal review required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid journal reviewer")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    if type(reason) is not str or reason not in ("amount", "account", "funding", "accounting_date", "source_evidence"):
        raise ValueError("Unsupported journal correction reason")
    organisation, journal = (UUID(str(value)) for value in (organisation_id, journal_id))

    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "record_expense_journal_correction")
            cursor.execute("SELECT * FROM omnixat_extraction.record_expense_journal_correction(%s,%s,%s,%s,%s)",
                           (organisation, journal, bytes.fromhex(snapshot_sha256), reason, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Journal correction target is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseJournalCorrectionConflict("A different correction reason already exists")
        if row["outcome"] != "stored":
            raise RuntimeError("Journal correction receipt unavailable")
        return ExpenseJournalCorrectionReceipt(journal, snapshot_sha256, reason, actor_id,
                                               row["correction_recorded_at"])


class ExpenseJournalClarificationConflict(Exception):
    """A different answer already exists for the snapshot and reason."""


def record_expense_journal_clarification(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, reason: JournalCorrectionReason, correction_reviewer_id: str, answer: str,
) -> ExpenseJournalClarificationReceipt:
    """Save an attributed answer to a current correction question without editing the journal."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal clarification required")
    actor_id = actor.user_id
    for identity in (actor_id, correction_reviewer_id):
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 200 or "\0" in identity:
            raise ValueError("Invalid journal clarification attribution")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    if type(reason) is not str or reason not in ("amount", "account", "funding", "accounting_date", "source_evidence"):
        raise ValueError("Unsupported journal correction reason")
    if type(answer) is not str or not 1 <= len(answer) <= 1000 or not answer.strip() or not answer.isprintable():
        raise ValueError("A single-line clarification of up to 1000 characters is required")
    organisation, journal = (UUID(str(value)) for value in (organisation_id, journal_id))

    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
        "expense_journal_clarification_answers",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "record_expense_journal_clarification")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.record_expense_journal_clarification(%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, journal, bytes.fromhex(snapshot_sha256), correction_reviewer_id, reason,
                  answer, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Journal clarification target is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseJournalClarificationConflict("A different clarification already exists")
        if row["outcome"] != "stored":
            raise RuntimeError("Journal clarification receipt unavailable")
        return ExpenseJournalClarificationReceipt(journal, snapshot_sha256, reason, row["correction_reviewer"],
                                                  actor_id, row["recorded_at"])


class ExpenseJournalEvidenceLinkConflict(Exception):
    """A different evidence link already exists for this clarification."""


def link_expense_journal_clarification_evidence(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, reason: JournalCorrectionReason, evidence_id: UUID,
) -> ExpenseJournalEvidenceLink:
    """Record a supporting evidence reference for an answered journal correction."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal clarification required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid journal clarification attribution")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    if type(reason) is not str or reason not in ("amount", "account", "funding", "accounting_date", "source_evidence"):
        raise ValueError("Unsupported journal correction reason")
    organisation, journal, evidence = (UUID(str(value)) for value in (organisation_id, journal_id, evidence_id))

    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
        "expense_journal_clarification_answers", "expense_journal_clarification_evidence",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "link_expense_journal_clarification_evidence")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.link_expense_journal_clarification_evidence(%s,%s,%s,%s,%s,%s)
            """, (organisation, journal, bytes.fromhex(snapshot_sha256), reason, evidence, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Journal clarification or supporting evidence is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseJournalEvidenceLinkConflict("A different evidence link already exists")
        if row["outcome"] != "stored":
            raise RuntimeError("Journal clarification evidence receipt unavailable")
        return ExpenseJournalEvidenceLink(journal, snapshot_sha256, reason, evidence, row["fingerprint"].hex(),
                                          row["scan_policy"], actor_id, row["recorded_at"])


@dataclass(frozen=True)
class ExpenseJournalAmountCorrection:
    journal_id: UUID
    snapshot_sha256: str
    evidence_id: UUID
    extraction_job_id: UUID
    source_cell: AmountCell
    content_sha256: str = field(repr=False)
    scan_policy_version: str
    currency: Literal["GBP"]
    previous_pence: int = field(repr=False)
    proposed_lines: tuple[JournalPreviewLine, JournalPreviewLine]


def preview_expense_journal_amount_correction(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, extraction_job_id: UUID, cell: AmountCell, currency: Literal["GBP"],
) -> ExpenseJournalAmountCorrection:
    """Preview replacement amounts from one extracted cell in the linked original."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal preparation required")
    if currency != "GBP":
        raise ValueError("Explicit GBP currency required")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    _validate_cell(cell)
    organisation, journal, job = (UUID(str(value)) for value in (organisation_id, journal_id, extraction_job_id))
    with _tenant_transaction(connection, tenant, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
        "expense_journal_clarification_answers", "expense_journal_clarification_evidence",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_amount_correction")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.read_expense_journal_amount_correction(%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, journal, bytes.fromhex(snapshot_sha256), job, cell.field_name, cell.row, cell.column))
            row = cursor.fetchone()
    if row is None:
        raise EvidenceNotEligible("Journal amount correction source is unavailable")
    return _amount_correction_details(row, journal, snapshot_sha256, job, cell)


def _amount_correction_details(row, journal, snapshot_sha256, job, cell):
    pence = expense_pence(Decimal(row["amount"]))
    return ExpenseJournalAmountCorrection(
        journal, snapshot_sha256, row["evidence_id"], job, cell, row["content_sha256"].hex(),
        row["policy_version"], "GBP", int(row["previous_pence"]),
        (JournalPreviewLine(row["expense_account_id"], "debit", pence),
         JournalPreviewLine(row["counterpart_account_id"], "credit", pence)),
    )


class ExpenseJournalAmountCorrectionConflict(Exception):
    """A different amount-correction proposal exists for this snapshot."""


@dataclass(frozen=True)
class ExpenseJournalAmountCorrectionReceipt:
    id: UUID
    journal_id: UUID
    snapshot_sha256: str
    created_at: datetime


def create_expense_journal_amount_correction(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, extraction_job_id: UUID, cell: AmountCell, currency: Literal["GBP"],
) -> ExpenseJournalAmountCorrectionReceipt:
    """Save a source-derived proposal while leaving the journal intact."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal preparation required")
    if currency != "GBP":
        raise ValueError("Explicit GBP currency required")
    if type(snapshot_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("An exact journal snapshot digest is required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid correction proposal attribution")
    _validate_cell(cell)
    organisation, journal, job = (UUID(str(value)) for value in (organisation_id, journal_id, extraction_job_id))
    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
        "expense_journal_clarification_answers", "expense_journal_clarification_evidence",
        "expense_journal_amount_corrections",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "create_expense_journal_amount_correction")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.create_expense_journal_amount_correction(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, journal, bytes.fromhex(snapshot_sha256), job, cell.field_name, cell.row, cell.column,
                  currency, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Journal amount correction source is unavailable")
        if row["outcome"] == "invalid_amount":
            raise ValueError("Correction amount must be positive and exact to a penny")
        if row["outcome"] == "conflict":
            raise ExpenseJournalAmountCorrectionConflict("A different correction proposal already exists")
        if row["outcome"] != "stored":
            raise RuntimeError("Correction proposal receipt unavailable")
        return ExpenseJournalAmountCorrectionReceipt(row["proposal_id"], journal, snapshot_sha256, row["recorded_at"])



@dataclass(frozen=True)
class ExpenseJournalAmountCorrectionReview:
    receipt: ExpenseJournalAmountCorrectionReceipt
    created_by: str = field(repr=False)
    proposal: ExpenseJournalAmountCorrection
    proposal_sha256: str


def read_expense_journal_amount_correction(
    connection, actor, tenant_id, organisation_id, proposal_id,
) -> ExpenseJournalAmountCorrectionReview:
    """Review one saved proposal only while its journal and exact source remain eligible."""
    tenant = _authorize(actor, tenant_id, "records:read")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal review required")
    organisation, proposal = (UUID(str(value)) for value in (organisation_id, proposal_id))
    with _tenant_transaction(connection, tenant, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
        "expense_journal_clarification_answers", "expense_journal_clarification_evidence",
        "expense_journal_amount_corrections",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_amount_correction_review")
            cursor.execute("SELECT * FROM omnixat_extraction.read_expense_journal_amount_correction_review(%s,%s)",
                           (organisation, proposal))
            row = cursor.fetchone()
    if row is None:
        raise EvidenceNotEligible("Journal correction proposal is unavailable")
    digest = row["snapshot_sha256"].hex()
    receipt = ExpenseJournalAmountCorrectionReceipt(row["proposal_id"], row["journal_id"], digest, row["created_at"])
    cell = AmountCell(row["field_name"], row["source_row"], row["source_column"])
    details = _amount_correction_details(row, row["journal_id"], digest, row["job_id"], cell)
    return ExpenseJournalAmountCorrectionReview(receipt, row["created_by"], details, row["proposal_sha256"].hex())



class ExpenseJournalAmountCorrectionDecisionConflict(Exception):
    """The reviewer already recorded a different decision for this exact proposal."""


@dataclass(frozen=True)
class ExpenseJournalAmountCorrectionDecisionReceipt:
    proposal_id: UUID
    proposal_sha256: str
    decision: JournalDecision
    reviewer_id: str = field(repr=False)
    recorded_at: datetime


def record_expense_journal_amount_correction_decision(
    connection, actor, tenant_id, organisation_id, proposal_id, *,
    proposal_sha256: str, decision: JournalDecision,
) -> ExpenseJournalAmountCorrectionDecisionReceipt:
    """Record a human bookkeeping observation against the exact eligible proposal."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal review required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid correction proposal reviewer")
    if type(proposal_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", proposal_sha256):
        raise ValueError("An exact proposal digest is required")
    if decision not in ("reviewed", "changes_requested"):
        raise ValueError("Unsupported correction proposal decision")
    organisation, proposal = (UUID(str(value)) for value in (organisation_id, proposal_id))
    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        *_DRAFT_TABLES, "expense_journal_review_decisions", "expense_journal_correction_requests",
        "expense_journal_clarification_answers", "expense_journal_clarification_evidence",
        "expense_journal_amount_corrections", "expense_journal_amount_correction_decisions",
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "record_expense_journal_amount_correction_decision")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.record_expense_journal_amount_correction_decision(%s,%s,%s,%s,%s)
            """, (organisation, proposal, bytes.fromhex(proposal_sha256), decision, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Journal correction proposal is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseJournalAmountCorrectionDecisionConflict("A different proposal decision already exists")
        if row["outcome"] != "stored":
            raise RuntimeError("Correction proposal decision receipt unavailable")
        return ExpenseJournalAmountCorrectionDecisionReceipt(
            proposal, proposal_sha256, decision, actor_id, row["decision_recorded_at"],
        )
