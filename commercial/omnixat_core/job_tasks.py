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


@dataclass(frozen=True)
class JournalPreparationPlan:
    """Explicit proposed funding references; no default payer, amount or approval."""
    funding_source_id: UUID
    payer_id: UUID = field(repr=False)
    funding_kind: str
    counterpart_account_id: UUID
    format_version: int = field(default=1, init=False)

    def __post_init__(self):
        if any(type(value) is not UUID or value.int == 0 for value in (
            self.funding_source_id, self.payer_id, self.counterpart_account_id,
        )):
            raise ValueError('Nonzero funding source, payer and counterpart UUIDs required')
        if type(self.funding_kind) is not str or self.funding_kind not in ('business_funds', 'personal_funds'):
            raise ValueError('Explicit supported funding kind required')

    def payload(self):
        return {'funding_source_id': str(self.funding_source_id), 'payer_id': str(self.payer_id),
                'funding_kind': self.funding_kind, 'counterpart_account_id': str(self.counterpart_account_id)}

    @classmethod
    def from_payload(cls, payload):
        if (type(payload) is not dict or set(payload) != {
            'funding_source_id', 'payer_id', 'funding_kind', 'counterpart_account_id',
        } or any(type(value) is not str for value in payload.values())):
            raise ValueError('Invalid saved journal preparation plan')
        plan = cls(UUID(payload['funding_source_id']), UUID(payload['payer_id']),
                   payload['funding_kind'], UUID(payload['counterpart_account_id']))
        if plan.payload() != payload:
            raise ValueError('Non-canonical saved journal preparation plan')
        return plan
