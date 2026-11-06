"""Read currently eligible CSV candidates and prepare prompts for unresolved cells."""

from dataclasses import dataclass, field
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
class CSVClarificationAnswer:
    cell: AmountCell
    amount: Decimal | None = field(repr=False)
    answered_by: str = field(repr=False)
    answered_at: datetime


@dataclass(frozen=True)
class CSVExtractionReview:
    job_id: UUID
    evidence_id: UUID
    policy_version: str
    extractor_version: str
    content_sha256: str
    stored_at: datetime
    amounts: tuple[CellAmount, ...]
    answers: tuple[CSVClarificationAnswer, ...] = ()

    @property
    def clarifications(self) -> tuple[CSVClarification, ...]:
        answered = {answer.cell for answer in self.answers}
        return tuple(CSVClarification(value.cell, value.status, _QUESTIONS[value.status])
                     for value in self.amounts if value.status != "found" and value.cell not in answered)


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


def _decode_answers(answers, amounts):
    unresolved = {value.cell for value in amounts if value.status in _QUESTIONS}
    if not isinstance(answers, list) or len(answers) > len(unresolved):
        raise EvidenceNotEligible("CSV review is unavailable")
    output = {}
    for item in answers:
        if not isinstance(item, dict) or set(item) != {
            "field_name", "row", "column", "amount", "answered_by", "answered_at",
        }:
            raise EvidenceNotEligible("CSV review is unavailable")
        name, row, column = (item[key] for key in ("field_name", "row", "column"))
        if not isinstance(name, str) or type(row) is not int or type(column) is not int:
            raise EvidenceNotEligible("CSV review is unavailable")
        cell = AmountCell(name, row, column)
        value, actor, timestamp = (item[key] for key in ("amount", "answered_by", "answered_at"))
        if (
            cell not in unresolved or cell in output
            or (value is not None and (not isinstance(value, str) or not _DECIMAL.fullmatch(value)))
            or not isinstance(actor, str) or not actor.strip() or len(actor) > 200
            or not isinstance(timestamp, str) or not timestamp.endswith("Z")
        ):
            raise EvidenceNotEligible("CSV review is unavailable")
        try:
            answered_at = datetime.fromisoformat(timestamp)
        except ValueError:
            raise EvidenceNotEligible("CSV review is unavailable") from None
        output[cell] = CSVClarificationAnswer(cell, Decimal(value) if value is not None else None, actor, answered_at)
    return tuple(output[value.cell] for value in amounts if value.cell in output)


def read_csv_extraction_review(connection, actor, tenant_id, organisation_id, evidence_id, job_id) -> CSVExtractionReview:
    """Read one eligible result with a verified interactive tenant principal and review-only login."""
    tenant = _authorize(actor, tenant_id, "evidence:read")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant evidence review required")
    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    with _tenant_transaction(connection, tenant, tables_required=(*_TABLES, "csv_extraction_results", "csv_clarification_answers")):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT CASE WHEN has_schema_privilege('omnixat_extraction', 'USAGE') THEN
                    has_function_privilege('omnixat_extraction.read_eligible_original(uuid,uuid)', 'EXECUTE')
                    OR has_function_privilege('omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)', 'EXECUTE')
                    OR has_function_privilege('omnixat_extraction.store_csv_answer(uuid,uuid,uuid,text,integer,integer,text,text)', 'EXECUTE')
                    ELSE false END
                    OR has_schema_privilege('omnixat', 'USAGE,CREATE')
                    OR has_schema_privilege('omnixat_extraction', 'CREATE')
                    AS overprivileged
            """)
            if cursor.fetchone()["overprivileged"]:
                raise PermissionError("Dedicated review grants required")
            cursor.execute(
                "SELECT * FROM omnixat_extraction.read_csv_review_with_answers(%s,%s,%s)",
                (organisation, evidence, job),
            )
            row = cursor.fetchone()
    if row is None or row["extractor_version"] != "csv-amount-v1":
        raise EvidenceNotEligible("CSV review is unavailable")
    amounts = _decode_amounts(row["amounts"])
    return CSVExtractionReview(job, evidence, row["policy_version"], row["extractor_version"],
                               row["content_sha256"].hex(), row["stored_at"], amounts,
                               _decode_answers(row["answers"], amounts))


class CSVClarificationConflict(Exception):
    """The cell already has a different recorded answer."""


@dataclass(frozen=True)
class CSVClarificationReceipt:
    job_id: UUID
    evidence_id: UUID
    cell: AmountCell
    answered_at: datetime


def store_csv_clarification(
    connection, actor, tenant_id, organisation_id, evidence_id, job_id, cell: AmountCell, *,
    amount: str | None,
) -> CSVClarificationReceipt:
    """Record a human answer; explicit None marks the amount unavailable."""
    tenant = _authorize(actor, tenant_id, "evidence:clarify")
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("Interactive tenant clarification required")
    actor_id = actor.user_id
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 200 or "\0" in actor_id:
        raise ValueError("Invalid answer attribution")
    if (
        type(cell) is not AmountCell or not isinstance(cell.field_name, str) or not _FIELD.fullmatch(cell.field_name)
        or type(cell.row) is not int or not 1 <= cell.row <= _MAX_ROWS
        or type(cell.column) is not int or not 1 <= cell.column <= _MAX_COLUMNS
    ):
        raise ValueError("Invalid clarification cell")
    if amount is not None and (not isinstance(amount, str) or not _DECIMAL.fullmatch(amount)):
        raise ValueError("Expected an exact decimal string or unavailable amount")

    organisation, evidence, job = (UUID(str(value)) for value in (organisation_id, evidence_id, job_id))
    tables = (*_TABLES, "csv_extraction_results", "csv_clarification_answers")
    with _tenant_transaction(connection, tenant, write=True, tables_required=tables):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT CASE WHEN has_schema_privilege('omnixat_extraction', 'USAGE') THEN
                    has_function_privilege('omnixat_extraction.read_eligible_original(uuid,uuid)', 'EXECUTE')
                    OR has_function_privilege('omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)', 'EXECUTE')
                    OR has_function_privilege('omnixat_extraction.read_csv_review(uuid,uuid,uuid)', 'EXECUTE')
                    OR has_function_privilege('omnixat_extraction.read_csv_review_with_answers(uuid,uuid,uuid)', 'EXECUTE')
                    ELSE false END
                    OR has_schema_privilege('omnixat', 'USAGE,CREATE')
                    OR has_schema_privilege('omnixat_extraction', 'CREATE')
                    AS overprivileged
            """)
            if cursor.fetchone()["overprivileged"]:
                raise PermissionError("Dedicated clarification grants required")
            cursor.execute("""
                SELECT * FROM omnixat_extraction.store_csv_answer(%s,%s,%s,%s,%s,%s,%s,%s)
            """, (organisation, evidence, job, cell.field_name, cell.row, cell.column, amount, actor_id))
            row = cursor.fetchone()
            if row["outcome"] == "ineligible":
                raise EvidenceNotEligible("CSV clarification is unavailable")
            if row["outcome"] == "conflict":
                raise CSVClarificationConflict("A different clarification answer already exists")
            if row["outcome"] != "stored":
                raise RuntimeError("Clarification receipt unavailable")
            return CSVClarificationReceipt(job, evidence, cell, row["stored_at"])
