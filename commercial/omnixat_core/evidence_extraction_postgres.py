"""Read one admitted original for a trusted extraction job and read explicitly selected CSV amounts."""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .evidence_csv import AmountCell, CellAmount, EvidenceCSVError, read_csv_amounts
from .evidence_intake import MAX_EVIDENCE_BYTES
from .postgres import _tenant_transaction

_TABLES = (
    "evidence_registrations", "evidence_quarantine", "evidence_scan_verdicts", "evidence_scan_claims",
)


class EvidenceNotEligible(Exception):
    """The evidence could not be admitted for extraction."""


@dataclass(frozen=True)
class AdmittedEvidence:
    evidence_id: UUID
    policy_version: str
    media_type: str
    content_sha256: str
    original_bytes: bytes = field(repr=False)


def _require_extraction_role(cursor):
    cursor.execute("""
        SELECT has_schema_privilege('omnixat', 'USAGE,CREATE')
            OR has_schema_privilege('omnixat_extraction', 'CREATE')
            AS overprivileged
    """)
    if cursor.fetchone()["overprivileged"]:
        raise PermissionError("Dedicated extraction gate grants required")


def read_evidence_for_extraction(connection, tenant_id, organisation_id, evidence_id) -> AdmittedEvidence:
    """Use only a server-verified job's scope and a dedicated execute-only login."""
    tenant, organisation, evidence = (UUID(str(value)) for value in (tenant_id, organisation_id, evidence_id))
    with _tenant_transaction(connection, tenant, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_extraction_role(cursor)
            cursor.execute("SELECT * FROM omnixat_extraction.read_eligible_original(%s,%s)", (organisation, evidence))
            row = cursor.fetchone()
    if row is None:
        raise EvidenceNotEligible("Evidence is not eligible for extraction")
    original = row["original_bytes"]
    digest = row["content_sha256"]
    if not isinstance(original, bytes) or not 1 <= len(original) == row["byte_size"] <= MAX_EVIDENCE_BYTES or (
        sha256(original).digest() != digest
    ):
        raise EvidenceNotEligible("Evidence is not eligible for extraction")
    return AdmittedEvidence(evidence, row["policy_version"], row["media_type"], digest.hex(), original)


@dataclass(frozen=True)
class CSVAmountExtraction:
    evidence_id: UUID
    policy_version: str
    content_sha256: str
    amounts: tuple[CellAmount, ...]


def extract_csv_amounts(
    connection, tenant_id, organisation_id, evidence_id, selections: tuple[AmountCell, ...],
) -> CSVAmountExtraction:
    """Run the bounded CSV reader only after admission; no result is persisted."""
    admitted = read_evidence_for_extraction(connection, tenant_id, organisation_id, evidence_id)
    if admitted.media_type != "text/csv":
        raise EvidenceCSVError("CSV extraction requires text/csv evidence")
    return CSVAmountExtraction(
        admitted.evidence_id, admitted.policy_version, admitted.content_sha256,
        read_csv_amounts(admitted.original_bytes, selections),
    )


class CSVExtractionConflict(Exception):
    """The job ID is already bound to a different extraction result."""


@dataclass(frozen=True)
class CSVExtractionReceipt:
    job_id: UUID
    evidence_id: UUID
    stored_at: datetime


def _store_csv_extraction(connection, tenant, organisation, job, result):
    # Persist decimal text, including the original scale; never convert to float.
    amounts = [
        {
            "field_name": value.cell.field_name, "row": value.cell.row, "column": value.cell.column,
            "status": value.status, "amount": str(value.amount) if value.amount is not None else None,
        }
        for value in result.amounts
    ]
    with _tenant_transaction(connection, tenant, write=True, tables_required=(*_TABLES, "csv_extraction_results")):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_extraction_role(cursor)
            cursor.execute("""
                SELECT * FROM omnixat_extraction.store_csv_result(%s,%s,%s,%s,%s,%s)
            """, (organisation, result.evidence_id, job, result.policy_version,
                  bytes.fromhex(result.content_sha256), Jsonb(amounts)))
            row = cursor.fetchone()
            if row["outcome"] == "ineligible":
                raise EvidenceNotEligible("Evidence is not eligible for extraction")
            if row["outcome"] == "conflict":
                raise CSVExtractionConflict("Extraction job already has a different result")
            if row["outcome"] != "stored":
                raise RuntimeError("Extraction receipt unavailable")
            return CSVExtractionReceipt(job, result.evidence_id, row["stored_at"])


def extract_and_store_csv_amounts(
    connection, tenant_id, organisation_id, evidence_id, job_id, selections: tuple[AmountCell, ...],
) -> CSVExtractionReceipt:
    """Use a stable, server-assigned job ID; a retry must repeat the same plan."""
    tenant, organisation, job = (UUID(str(value)) for value in (tenant_id, organisation_id, job_id))
    result = extract_csv_amounts(connection, tenant, organisation, evidence_id, selections)
    return _store_csv_extraction(connection, tenant, organisation, job, result)
