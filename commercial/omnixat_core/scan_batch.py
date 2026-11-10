"""Validate an operator-owned finite manifest before dispatching any work."""
from uuid import UUID


def validate_evidence_batch(items):
    if not isinstance(items,list) or not 1 <= len(items) <= 5:
        raise ValueError('A batch requires one to five evidence IDs')
    if any(not isinstance(item,str) or str(UUID(item)) != item for item in items):
        raise ValueError('Canonical evidence IDs required')
    if len(set(items)) != len(items):
        raise ValueError('Duplicate evidence IDs')
    return tuple(items)
