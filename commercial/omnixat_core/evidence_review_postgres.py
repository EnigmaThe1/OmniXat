"""Read currently eligible CSV candidates and prepare prompts for unresolved cells."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_csv import AmountCell, CellAmount, _DECIMAL, _FIELD, _MAX_COLUMNS, _MAX_ROWS, _MAX_SELECTIONS
from .evidence_extraction_postgres import EvidenceNotEligible, _TABLES
from .evidence_postgres import _authorize
from .postgres import _tenant_transaction

_QUESTIONS = {
    "missing": "Which cell contains this amount, or is the amount unavailable?",
    "blank": "What amount belongs in this blank cell, or should it remain blank?",
    "ambiguous": "What exact decimal amount does this cell represent?",
}


@dataclass(frozen=True)
class CSVClarification:
    cell: AmountCell
    reason: str
    question: str


@dataclass(frozen=True)
class CSVExtractionReview:
    job_id: UUID
    evidence_id: UUID
    policy_version: str
    extractor_version: str
    content_sha256: str
    stored_at: datetime
    amounts: tuple[CellAmount, ...]

    @property
    def clarifications(self) -> tuple[CSVClarification, ...]:
        return tuple(CSVClarification(value.cell, value.status, _QUESTIONS[value.status])
                     for value in self.amounts if value.status != "found")


def _decode_amounts(amounts):
    if not isinstance(amounts, list) or not 1 <= len(amounts) <= _MAX_SELECTIONS:
        raise EvidenceNotEligible("CSV review is unavailable")
    names = set()
    output = []
    for item in amounts:
        if not isinstance(item, dict) or set(item) != {"field_name", "row", "column", "status", "amount"}:
            raise EvidenceNotEligible("CSV review is unavailable")
        name, row, column, status, value = (item[key] for key in ("field_name", "row", "column", "status", "amount"))
        if (
            not isinstance(name, str) or not _FIELD.fullmatch(name) or name in names
            or type(row) is not int or not 1 <= row <= _MAX_ROWS
            or type(column) is not int or not 1 <= column <= _MAX_COLUMNS
            or not isinstance(status, str) or (status != "found" and status not in _QUESTIONS)
        ):
            raise EvidenceNotEligible("CSV review is unavailable")
        if status == "found":
            if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
                raise EvidenceNotEligible("CSV review is unavailable")
        elif value is not None:
            raise EvidenceNotEligible("CSV review is unavailable")
        names.add(name)
        output.append(CellAmount(AmountCell(name, row, column), status, Decimal(value) if status == "found" else None))
    return tuple(output)


def read_csv_extraction_review(connection, actor, tenant_id, organisation_id, evidence_id, job_id) -> CSVExtractionReview:
    """Read one eligible result with a verified interactive tenant principal and review-only login."""
    tenant = _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant evidence review required")
    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    with _tenant_transaction(connection, tenant, tables_required=(*_TABLES, "csv_extraction_results")):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT CASE WHEN has_schema_privilege('omnixat_extraction', 'USAGE') THEN
                    has_function_privilege('omnixat_extraction.read_eligible_original(uuid,uuid)', 'EXECUTE')
                    OR has_function_privilege('omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)', 'EXECUTE')
                    ELSE false END
                    OR has_schema_privilege('omnixat', 'USAGE,CREATE')
                    OR has_schema_privilege('omnixat_extraction', 'CREATE')
                    AS overprivileged
            """)
            if cursor.fetchone()["overprivileged"]:
                raise PermissionError("Dedicated review grants required")
            cursor.execute("SELECT * FROM omnixat_extraction.read_csv_review(%s,%s,%s)", (organisation, evidence, job))
            row = cursor.fetchone()
    if row is None or row["extractor_version"] != "csv-amount-v1":
        raise EvidenceNotEligible("CSV review is unavailable")
    return CSVExtractionReview(job, evidence, row["policy_version"], row["extractor_version"],
                               row["content_sha256"].hex(), row["stored_at"], _decode_amounts(row["amounts"]))
