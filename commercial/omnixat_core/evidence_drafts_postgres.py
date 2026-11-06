"""Prepare a draft amount from an exact eligible evidence cell; never post it."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_csv import AmountCell, _FIELD, _MAX_COLUMNS, _MAX_ROWS
from .evidence_extraction_postgres import EvidenceNotEligible, _TABLES
from .evidence_postgres import _authorize
from .postgres import _tenant_transaction


class EvidenceDraftConflict(Exception):
    """A different draft already exists for this extraction field."""


@dataclass(frozen=True)
class EvidenceDraftReceipt:
    evidence_id: UUID
    job_id: UUID
    cell: AmountCell
    source_kind: Literal["extracted", "clarified"]
    created_at: datetime


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
    if (
        type(cell) is not AmountCell or not isinstance(cell.field_name, str) or not _FIELD.fullmatch(cell.field_name)
        or type(cell.row) is not int or not 1 <= cell.row <= _MAX_ROWS
        or type(cell.column) is not int or not 1 <= cell.column <= _MAX_COLUMNS
    ):
        raise ValueError("Invalid draft source cell")

    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    tables = (*_TABLES, "csv_extraction_results", "csv_clarification_answers", "evidence_draft_amounts")
    with _tenant_transaction(connection, tenant, write=True, tables_required=tables):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT has_schema_privilege('omnixat', 'USAGE,CREATE')
                    OR has_schema_privilege('omnixat_extraction', 'CREATE')
                    OR EXISTS (
                        SELECT 1 FROM pg_catalog.pg_proc p
                        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = 'omnixat_extraction' AND p.proname <> 'create_csv_draft_amount'
                          AND has_function_privilege(p.oid, 'EXECUTE')
                    ) AS overprivileged
            """)
            if cursor.fetchone()["overprivileged"]:
                raise PermissionError("Dedicated draft grants required")
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
