"""Prepare, save and review two-line expense journal drafts without posting."""

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_csv import AmountCell
from .evidence_drafts_postgres import _require_draft_role
from .evidence_extraction_postgres import EvidenceNotEligible
from .evidence_postgres import _authorize
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
class ExpenseJournalDecisionPage:
    decisions: tuple[ExpenseJournalDecisionReceipt, ...]
    next_after_reviewer: str | None = field(repr=False)
    corrections: tuple[ExpenseJournalCorrectionReceipt, ...] = ()

    @property
    def follow_up_questions(self) -> tuple[ExpenseJournalFollowUpQuestion, ...]:
        return journal_correction_questions(correction.reason for correction in self.corrections)


def read_expense_journal_decisions(
    connection, actor, tenant_id, organisation_id, journal_id, *,
    snapshot_sha256: str, page_size: int = 25, after_reviewer: str | None = None,
) -> ExpenseJournalDecisionPage:
    """Read observations and their attached corrections for one eligible snapshot."""
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
                                              "expense_journal_correction_requests")):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_decisions_with_corrections")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.read_expense_journal_decisions_with_corrections(%s,%s,%s,%s,%s)
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
    return ExpenseJournalDecisionPage(decisions, next_cursor, corrections)


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
