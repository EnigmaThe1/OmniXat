"""Deterministic, bounded extraction of decimal values at explicit CSV coordinates."""

import csv
from dataclasses import dataclass, field
from decimal import Decimal
import io
import re
from typing import Literal

_MAX_BYTES = 512 * 1024
_MAX_ROWS = 5_000
_MAX_COLUMNS = 64
_MAX_CELL_CHARS = 4_096
_MAX_SELECTIONS = 32
_DECIMAL = re.compile(r"[+-]?[0-9]{1,18}(?:\.[0-9]{1,6})?")
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}")


class EvidenceCSVError(ValueError):
    """CSV input or its extraction plan is outside the supported format."""


@dataclass(frozen=True)
class AmountCell:
    field_name: str
    row: int
    column: int


@dataclass(frozen=True)
class CellAmount:
    cell: AmountCell
    status: Literal["found", "missing", "blank", "ambiguous"]
    amount: Decimal | None = field(default=None, repr=False)


def validate_amount_cells(selections: tuple[AmountCell, ...]) -> tuple[AmountCell, ...]:
    """Validate a bounded reference-only selection without reading a document."""
    if not isinstance(selections, tuple) or not 1 <= len(selections) <= _MAX_SELECTIONS:
        raise EvidenceCSVError("Expected a bounded tuple of amount cells")
    names = set()
    for cell in selections:
        if (
            type(cell) is not AmountCell
            or not isinstance(cell.field_name, str) or not _FIELD.fullmatch(cell.field_name)
            or cell.field_name in names
            or type(cell.row) is not int or not 1 <= cell.row <= _MAX_ROWS
            or type(cell.column) is not int or not 1 <= cell.column <= _MAX_COLUMNS
        ):
            raise EvidenceCSVError("Invalid or duplicate amount cell selection")
        names.add(cell.field_name)
    return selections


def read_csv_amounts(original: bytes, selections: tuple[AmountCell, ...]) -> tuple[CellAmount, ...]:
    """Use one-based logical CSV record and column numbers, including header rows."""
    selections = validate_amount_cells(selections)
    by_row = {}
    for cell in selections:
        by_row.setdefault(cell.row, []).append(cell)

    if not isinstance(original, bytes) or not 1 <= len(original) <= _MAX_BYTES:
        raise EvidenceCSVError("CSV exceeds input limits or is empty")
    try:
        text = original.decode("utf-8-sig")
    except UnicodeError:
        raise EvidenceCSVError("CSV must be UTF-8") from None
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        raise EvidenceCSVError("CSV contains unsupported control characters")
    results = {cell.field_name: CellAmount(cell, "missing") for cell in selections}
    reader = csv.reader(io.StringIO(text, newline=""), dialect="excel", strict=True)
    try:
        for number, row in enumerate(reader, start=1):
            if number > _MAX_ROWS or len(row) > _MAX_COLUMNS or any(len(x) > _MAX_CELL_CHARS for x in row):
                raise EvidenceCSVError("CSV exceeds row, column or cell limits")
            for cell in by_row.get(number, ()):
                if cell.column > len(row):
                    continue
                value = row[cell.column - 1].strip(" \t")
                if not value:
                    results[cell.field_name] = CellAmount(cell, "blank")
                elif _DECIMAL.fullmatch(value):
                    results[cell.field_name] = CellAmount(cell, "found", Decimal(value))
                else:
                    results[cell.field_name] = CellAmount(cell, "ambiguous")
    except csv.Error:
        raise EvidenceCSVError("Malformed CSV") from None
    return tuple(results[cell.field_name] for cell in selections)
