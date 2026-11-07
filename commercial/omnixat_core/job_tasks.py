"""Versioned reference-only task inputs; evidence contents are never task data."""
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from .evidence_csv import AmountCell, validate_amount_cells
from .expense_context import ExpenseDraftContext, validate_expense_context_inputs


@dataclass(frozen=True)
class EvidencePreparationTask:
    organisation_id: UUID
    evidence_id: UUID
    content_sha256: bytes = field(repr=False)
    version: int = field(default=1, init=False)
    kind: str = field(default="prepare_evidence", init=False)

    def __post_init__(self):
        if not isinstance(self.organisation_id, UUID) or not isinstance(self.evidence_id, UUID):
            raise ValueError("Organisation and evidence UUIDs required")
        if type(self.content_sha256) is not bytes or len(self.content_sha256) != 32:
            raise ValueError("An exact SHA-256 fingerprint is required")

    def payload(self):
        return {"version": self.version, "kind": self.kind,
                "organisation_id": str(self.organisation_id), "evidence_id": str(self.evidence_id),
                "content_sha256": self.content_sha256.hex()}


@dataclass(frozen=True)
class CSVExtractionPlan:
    """Ordered field references only; never store document values or prompts."""
    selections: tuple[AmountCell, ...]
    format_version: int = field(default=1, init=False)

    def __post_init__(self):
        validate_amount_cells(self.selections)

    def payload(self):
        return [{"field_name": cell.field_name, "row": cell.row, "column": cell.column} for cell in self.selections]

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, list) or any(type(item) is not dict or set(item) != {"field_name", "row", "column"}
                                               for item in payload):
            raise ValueError("Invalid saved CSV plan")
        return cls(tuple(AmountCell(**item) for item in payload))


@dataclass(frozen=True)
class ExpensePreparationPlan:
    """Explicit accounting context and source coordinates; never an amount or approval."""
    source_cell: AmountCell
    context: ExpenseDraftContext
    period_id: UUID
    format_version: int = field(default=1, init=False)

    def __post_init__(self):
        validate_amount_cells((self.source_cell,))
        validate_expense_context_inputs(self.context, self.period_id)

    def payload(self):
        return {'source_cell': {'field_name': self.source_cell.field_name,
                                'row': self.source_cell.row, 'column': self.source_cell.column},
                'currency': self.context.currency, 'accounting_date': self.context.accounting_date.isoformat(),
                'expense_account_id': str(self.context.expense_account_id), 'period_id': str(self.period_id)}

    @classmethod
    def from_payload(cls, payload):
        if (type(payload) is not dict or set(payload) != {
            'source_cell', 'currency', 'accounting_date', 'expense_account_id', 'period_id',
        } or type(payload['source_cell']) is not dict
            or set(payload['source_cell']) != {'field_name', 'row', 'column'}
            or any(type(payload[key]) is not str for key in ('currency', 'accounting_date', 'expense_account_id', 'period_id'))):
            raise ValueError('Invalid saved expense preparation plan')
        plan = cls(AmountCell(**payload['source_cell']),
                   ExpenseDraftContext(payload['currency'], date.fromisoformat(payload['accounting_date']),
                                       UUID(payload['expense_account_id'])), UUID(payload['period_id']))
        if plan.payload() != payload:
            raise ValueError('Non-canonical saved expense preparation plan')
        return plan
