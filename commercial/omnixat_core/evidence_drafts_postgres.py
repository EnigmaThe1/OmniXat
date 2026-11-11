"""Prepare a draft amount from an exact eligible evidence cell; never post it."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_csv import AmountCell, _DECIMAL, _FIELD, _MAX_COLUMNS, _MAX_ROWS
from .evidence_extraction_postgres import EvidenceNotEligible, _TABLES
from .evidence_postgres import _authorize
from .expense_context import ExpenseDraftContext, ExpenseDraftPolicy, expense_pence, validate_expense_context, validate_expense_context_inputs
from .postgres import _tenant_transaction

_DRAFT_TABLES = (*_TABLES, "csv_extraction_results", "csv_clarification_answers", "evidence_draft_amounts")


class EvidenceDraftConflict(Exception):
    """A different draft already exists for this extraction field."""


@dataclass(frozen=True)
class EvidenceDraftReceipt:
    evidence_id: UUID
    job_id: UUID
    cell: AmountCell
    source_kind: Literal["extracted", "clarified"]
    created_at: datetime


def _validate_cell(cell):
    if (
        type(cell) is not AmountCell or not isinstance(cell.field_name, str) or not _FIELD.fullmatch(cell.field_name)
        or type(cell.row) is not int or not 1 <= cell.row <= _MAX_ROWS
        or type(cell.column) is not int or not 1 <= cell.column <= _MAX_COLUMNS
    ):
        raise ValueError("Invalid draft source cell")


def _require_draft_role(cursor, allowed_function):
    cursor.execute("""
        SELECT has_schema_privilege('omnixat', 'USAGE,CREATE')
            OR has_schema_privilege('omnixat_extraction', 'CREATE')
            OR EXISTS (
                SELECT 1 FROM pg_catalog.pg_proc p
                JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'omnixat_extraction' AND p.proname <> %s
                  AND has_function_privilege(p.oid, 'EXECUTE')
            ) AS overprivileged
    """, (allowed_function,))
    if cursor.fetchone()["overprivileged"]:
        raise PermissionError("Dedicated draft grants required")


def create_csv_draft_amount(
    connection, actor, tenant_id, organisation_id, evidence_id, job_id, cell: AmountCell,
) -> EvidenceDraftReceipt:
    """Derive the amount in PostgreSQL; callers choose a source cell, never a value."""
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant draft preparation required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid draft attribution")
    _validate_cell(cell)

    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    with _tenant_transaction(connection, tenant, write=True, tables_required=_DRAFT_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "create_csv_draft_amount")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.create_csv_draft_amount(%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, evidence, job, cell.field_name, cell.row, cell.column, actor_id))
            row = cursor.fetchone()
            if row["outcome"] == "ineligible":
                raise EvidenceNotEligible("CSV draft amount is unavailable")
            if row["outcome"] == "conflict":
                raise EvidenceDraftConflict("A different draft already exists for this field")
            if row["outcome"] != "stored":
                raise RuntimeError("Draft receipt unavailable")
            return EvidenceDraftReceipt(evidence, job, cell, row["stored_source"], row["stored_at"])


@dataclass(frozen=True)
class EvidenceDraftAmount:
    receipt: EvidenceDraftReceipt
    amount: Decimal = field(repr=False)
    created_by: str = field(repr=False)
    policy_version: str
    content_sha256: str


def read_csv_draft_amount(
    connection, actor, tenant_id, organisation_id, evidence_id, job_id, cell: AmountCell,
) -> EvidenceDraftAmount:
    """Read one draft after rechecking its exact source under the current policy."""
    tenant = _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant draft review required")
    _validate_cell(cell)
    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    with _tenant_transaction(connection, tenant, tables_required=_DRAFT_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_csv_draft_amount")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.read_csv_draft_amount(%s,%s,%s,%s,%s,%s)
            """, (organisation, evidence, job, cell.field_name, cell.row, cell.column))
            row = cursor.fetchone()

    return _read_amount(row, evidence, job, cell)


def _read_amount(row, evidence, job, cell) -> EvidenceDraftAmount:
    if row is None or row["amount"] is None or not _DECIMAL.fullmatch(row["amount"]):
        raise EvidenceNotEligible("CSV draft amount is unavailable")
    receipt = EvidenceDraftReceipt(evidence, job, cell, row["source_kind"], row["created_at"])
    return EvidenceDraftAmount(receipt, Decimal(row["amount"]), row["created_by"],
                               row["policy_version"], row["content_sha256"].hex())


@dataclass(frozen=True)
class PreparedExpenseDraft:
    source: EvidenceDraftAmount
    context: ExpenseDraftContext
    period_id: UUID
    amount_pence: int = field(repr=False)


_EXPENSE_POLICY_TABLES = (*_DRAFT_TABLES, "expense_accounting_periods", "expense_account_policy")


def _expense_scope(actor, tenant_id, organisation_id, evidence_id, job_id, cell, context, period_id):
    tenant = _authorize(actor, tenant_id, "records:write")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant expense preparation required")
    validate_expense_context_inputs(context, period_id)
    _validate_cell(cell)
    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    return tenant, organisation, evidence, job


def prepare_csv_expense_draft(
    connection, actor, tenant_id, organisation_id, evidence_id, job_id, cell: AmountCell, *,
    context: ExpenseDraftContext, period_id: UUID,
) -> PreparedExpenseDraft:
    """Read the selected accounting context and eligible evidence in one snapshot."""
    tenant, organisation, evidence, job = _expense_scope(
        actor, tenant_id, organisation_id, evidence_id, job_id, cell, context, period_id,
    )
    with _tenant_transaction(connection, tenant, tables_required=_EXPENSE_POLICY_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_csv_expense_preview")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.read_csv_expense_preview(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, evidence, job, cell.field_name, cell.row, cell.column,
                  period_id, context.expense_account_id, context.accounting_date))
            row = cursor.fetchone()
    if row is None:
        raise ValueError("Selected period, date or expense account is unavailable")
    policy = ExpenseDraftPolicy(tenant, organisation, row["period_start"], row["period_end"],
                                frozenset({context.expense_account_id}))
    validate_expense_context(tenant, organisation, context, policy)
    source = _read_amount(row, evidence, job, cell)
    return PreparedExpenseDraft(source, context, period_id, expense_pence(source.amount))


class ExpenseDraftConflict(Exception):
    """The selected source amount already has a different expense draft."""


@dataclass(frozen=True)
class ExpenseDraftReceipt:
    id: UUID
    created_at: datetime
    amount_pence: int = field(repr=False)


def create_csv_expense_draft(
    connection, actor, tenant_id, organisation_id, evidence_id, job_id, cell: AmountCell, *,
    context: ExpenseDraftContext, period_id: UUID,
) -> ExpenseDraftReceipt:
    """Persist one draft per source amount; never post it to the ledger."""
    tenant, organisation, evidence, job = _expense_scope(
        actor, tenant_id, organisation_id, evidence_id, job_id, cell, context, period_id,
    )
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid draft attribution")
    with _tenant_transaction(connection, tenant, write=True, tables_required=(*_EXPENSE_POLICY_TABLES,
                                                                              "csv_expense_drafts")):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "create_csv_expense_draft")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.create_csv_expense_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, evidence, job, cell.field_name, cell.row, cell.column, period_id,
                  context.expense_account_id, context.accounting_date, context.currency, actor_id))
            row = cursor.fetchone()
    if row["outcome"] == "ineligible":
        raise EvidenceNotEligible("CSV draft amount is unavailable")
    if row["outcome"] == "context":
        raise ValueError("Selected period, date or expense account is unavailable")
    if row["outcome"] == "amount":
        raise ValueError("Expense amount must be positive, supported and exact to a penny")
    if row["outcome"] == "conflict":
        raise ExpenseDraftConflict("A different expense draft already exists for this source amount")
    if row["outcome"] != "stored":
        raise RuntimeError("Expense draft receipt unavailable")
    return ExpenseDraftReceipt(row["draft_id"], row["stored_at"], int(row["stored_pence"]))


@dataclass(frozen=True)
class ExpenseDraftReview:
    receipt: ExpenseDraftReceipt
    created_by: str = field(repr=False)
    context: ExpenseDraftContext
    period_id: UUID
    source: EvidenceDraftAmount


def read_csv_expense_draft(
    connection, actor, tenant_id, organisation_id, draft_id,
) -> ExpenseDraftReview:
    """Review one saved expense draft with fresh evidence and accounting policy checks."""
    tenant = _authorize(actor, tenant_id, "records:read")
    _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant expense review required")
    organisation, draft = (UUID(str(value)) for value in (organisation_id, draft_id))
    with _tenant_transaction(connection, tenant, tables_required=(*_EXPENSE_POLICY_TABLES,
                                                                  "csv_expense_drafts")):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, "read_csv_expense_draft")
            cursor.execute("SELECT * FROM omnixat_extraction.read_csv_expense_draft(%s,%s)",
                           (organisation, draft))
            row = cursor.fetchone()
    return _read_expense_draft(row)


def _read_expense_draft(row) -> ExpenseDraftReview:
    """Shared decoding/invariants after separately authorised database reads."""
    if row is None:
        raise EvidenceNotEligible("Expense draft is unavailable")
    cell = AmountCell(row["field_name"], row["source_row"], row["source_column"])
    source = _read_amount(row, row["evidence_id"], row["job_id"], cell)
    try:
        amount_pence = expense_pence(source.amount)
    except ValueError:
        raise EvidenceNotEligible("Expense draft is unavailable") from None
    if amount_pence != row["amount_pence"]:
        raise EvidenceNotEligible("Expense draft is unavailable")
    receipt = ExpenseDraftReceipt(row["draft_id"], row["expense_created_at"], amount_pence)
    context = ExpenseDraftContext(row["currency"], row["accounting_date"], row["expense_account_id"])
    return ExpenseDraftReview(receipt, row["expense_created_by"], context, row["period_id"], source)
