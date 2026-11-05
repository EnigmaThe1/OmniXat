"""Money prototype: exact Decimal operations; policy must be chosen per tax field."""
from decimal import Decimal, InvalidOperation

PENNY = Decimal('0.01')


def format_money(value: str | Decimal, *, rounding: str) -> str:
    """Quantize explicitly, never via binary floating-point.

    Example only: callers choose rounding from the appropriate statutory rule.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise TypeError('Money requires a decimal string or Decimal, never a float.')
    try:
        decimal = Decimal(value)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError('Invalid decimal amount.') from exc
    if not decimal.is_finite():
        raise ValueError('Non-finite monetary amount.')
    quantized = decimal.quantize(PENNY, rounding=rounding)
    return format(quantized, '.2f')
