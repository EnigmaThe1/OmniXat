"""Validation for the bounded GBP expense preparation workflow."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class ExpenseDraftContext:
    currency: str
    accounting_date: date
    expense_account_id: UUID


@dataclass(frozen=True)
class ExpenseDraftPolicy:
    """Trusted server configuration; never construct from a draft request."""

    tenant_id: UUID
    organisation_id: UUID
    period_start: date
    period_end: date
    expense_account_ids: frozenset[UUID]


def validate_expense_context(
    tenant: UUID, organisation: UUID, context: ExpenseDraftContext, policy: ExpenseDraftPolicy,
) -> None:
    if type(policy) is not ExpenseDraftPolicy or (
        type(policy.tenant_id) is not UUID or type(policy.organisation_id) is not UUID
        or (policy.tenant_id, policy.organisation_id) != (tenant, organisation)
    ):
        raise PermissionError("Expense draft policy does not cover this organisation")
    if (
        type(policy.period_start) is not date or type(policy.period_end) is not date
        or policy.period_start > policy.period_end
        or type(policy.expense_account_ids) is not frozenset
        or any(type(account) is not UUID or account.int == 0 for account in policy.expense_account_ids)
    ):
        raise ValueError("Invalid expense draft policy")
    if type(context) is not ExpenseDraftContext or context.currency != "GBP":
        raise ValueError("Explicit GBP currency required")
    if type(context.accounting_date) is not date or not policy.period_start <= context.accounting_date <= policy.period_end:
        raise ValueError("Accounting date must be inside the configured period")
    if type(context.expense_account_id) is not UUID or context.expense_account_id not in policy.expense_account_ids:
        raise ValueError("Select an eligible expense account")


def expense_pence(amount: Decimal) -> int:
    """Accept positive supported amounts with no fractional pence or rounding."""
    if not isinstance(amount, Decimal) or not amount.is_finite() or not Decimal("0.01") <= amount < Decimal("1e18"):
        raise ValueError("Expected a positive expense amount within supported bounds")
    # The parser supports up to six fractional places. Inspect representation
    # before using integer ratios to avoid unbounded exponent work.
    if amount.as_tuple().exponent < -6:
        raise ValueError("Expense amount exceeds source precision")
    numerator, denominator = amount.as_integer_ratio()
    pence, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise ValueError("Expense amount must be exact to a penny")
    return pence
