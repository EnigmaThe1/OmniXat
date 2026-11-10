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
