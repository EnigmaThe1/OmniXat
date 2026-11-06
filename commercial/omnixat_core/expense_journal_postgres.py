"""Preview a two-line expense journal without saving or posting it."""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_csv import AmountCell
from .evidence_drafts_postgres import _require_draft_role
from .evidence_extraction_postgres import EvidenceNotEligible
from .evidence_postgres import _authorize
from .expense_funding_postgres import _TABLES as _FUNDING_TABLES
from .postgres import _tenant_transaction

_TABLES = (*_FUNDING_TABLES, "expense_counterpart_policy")


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


def prepare_expense_journal_preview(
    connection, actor, tenant_id, organisation_id, draft_id, *, counterpart_account_id: UUID,
) -> ExpenseJournalPreview:
    """Check the selected counterpart and return two equal, opposing GBP lines."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant journal preparation required")
    if type(counterpart_account_id) is not UUID or not counterpart_account_id.int:
        raise ValueError("Select an explicit counterpart account")
    organisation, draft = (UUID(str(value)) for value in (organisation_id, draft_id))

    with _tenant_transaction(connection, tenant, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_expense_journal_preview")
            cursor.execute("SELECT * FROM omnixat_extraction.read_expense_journal_preview(%s,%s,%s)",
                           (organisation, draft, counterpart_account_id))
            row = cursor.fetchone()
    if row is None:
        raise EvidenceNotEligible("Expense draft, funding source or counterpart account is unavailable")
    pence = int(row["amount_pence"])
    return ExpenseJournalPreview(
        draft, row["funding_source_id"], row["currency"], row["accounting_date"], row["period_id"],
        row["evidence_id"], row["job_id"], AmountCell(row["field_name"], row["source_row"], row["source_column"]),
        row["policy_version"], row["content_sha256"].hex(),
        (JournalPreviewLine(row["expense_account_id"], "debit", pence),
         JournalPreviewLine(row["counterpart_account_id"], "credit", pence)),
    )
