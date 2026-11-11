"""Strict operator plan; source coordinates use the shared CSV validator."""
from uuid import UUID
from .evidence_csv import AmountCell, validate_amount_cells


def validate_extraction_plan(plan):
    if not isinstance(plan,dict) or set(plan)!={'tenant','organisation','evidence','job','selections'}:
        raise ValueError('Explicit extraction plan required')
    identifiers=[]
    for key in ['tenant','organisation','evidence','job']:
        value=plan[key]
        if not isinstance(value,str) or str(UUID(value))!=value:
            raise ValueError('Canonical scope and job IDs required')
        identifiers.append(value)
    cells=plan['selections']
    if not isinstance(cells,list) or not 1<=len(cells)<=32:
        raise ValueError('Bounded cell selections required')
    selections=[]
    for cell in cells:
        if not isinstance(cell,dict) or set(cell)!={'field_name','row','column'}:
            raise ValueError('Explicit source coordinates required')
        selections.append(AmountCell(**cell))
    return (*identifiers,validate_amount_cells(tuple(selections)))


def validate_extraction_batch(plans):
    """Snapshot the entire finite manifest before any database work."""
    if not isinstance(plans,list) or not 1<=len(plans)<=5:
        raise ValueError('One to five explicit extraction plans required')
    validated=tuple(validate_extraction_plan(plan) for plan in plans)
    if len({plan[:2] for plan in validated})!=1:
        raise ValueError('One tenant and organisation required')
    if len({plan[3] for plan in validated})!=len(validated):
        raise ValueError('Distinct job IDs required')
    return validated
