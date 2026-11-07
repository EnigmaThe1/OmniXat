"""Versioned reference-only task inputs; evidence contents are never task data."""
from dataclasses import dataclass, field
from uuid import UUID

from .evidence_csv import AmountCell, validate_amount_cells


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
