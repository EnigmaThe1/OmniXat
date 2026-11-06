"""Record who funded a draft expense without inferring accounting treatment."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_drafts_postgres import _EXPENSE_POLICY_TABLES, _require_draft_role
from .evidence_extraction_postgres import EvidenceNotEligible
from .evidence_postgres import _authorize
from .postgres import _tenant_transaction

_TABLES = (*_EXPENSE_POLICY_TABLES, "csv_expense_drafts", "expense_funding_sources", "expense_funding_context")


class ExpenseFundingConflict(Exception):
    """An eligible draft already has a different recorded funding selection."""


@dataclass(frozen=True)
class ExpenseFundingReceipt:
    draft_id: UUID
    funding_source_id: UUID
    payer_id: UUID = field(repr=False)
    funding_kind: Literal["business_funds", "personal_funds"]
    recorded_at: datetime


def record_expense_funding_context(
    connection, actor, tenant_id, organisation_id, draft_id, *, funding_source_id: UUID, payer_id: UUID,
) -> ExpenseFundingReceipt:
    """Record one explicit, attributed funding choice; never move funds or post a journal."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant expense preparation required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid funding attribution")
    if any(type(value) is not UUID or not value.int for value in (funding_source_id, payer_id)):
        raise ValueError("Select an explicit payer and funding source")
    organisation, draft = (UUID(str(value)) for value in (organisation_id, draft_id))

    with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "record_expense_funding_context")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.record_expense_funding_context(%s,%s,%s,%s,%s)
            """, (organisation, draft, funding_source_id, payer_id, actor_id))
            row = cursor.fetchone()
        if row["outcome"] == "unavailable":
            raise EvidenceNotEligible("Expense draft or funding selection is unavailable")
        if row["outcome"] == "conflict":
            raise ExpenseFundingConflict("A different funding selection already exists for this expense draft")
        if row["outcome"] != "stored":
            raise RuntimeError("Expense funding receipt unavailable")
        return ExpenseFundingReceipt(draft, funding_source_id, payer_id, row["funding_kind"], row["recorded_at"])
