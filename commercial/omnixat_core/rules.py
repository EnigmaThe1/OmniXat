"""Small, explicitly bounded compliance functions, not a full tax engine.

Applicability must be determined by the calling workflow. No function here
establishes eligibility for a tax regime, audit exemption or filing channel.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path

CATALOGUE = Path(__file__).parents[1] / "rules.json"


def catalogue():
    return json.loads(CATALOGUE.read_text())


def add_months(day: date, count: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + count, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


@dataclass(frozen=True)
class Obligation:
    kind: str
    due: date
    rule_id: str
    qualification: str


def ordinary_private_company_deadlines(period_end: date, *, confirmed_ordinary: bool):
    """Not for first, shortened, extended, public or special accounts periods."""
    if confirmed_ordinary is not True:
        raise ValueError("Confirm an ordinary subsequent private-company period.")
    return (
        Obligation("ch_accounts", add_months(period_end, 9), "CH-ORDINARY", "Ordinary subsequent private-company accounts only"),
        Obligation("ct600", add_months(period_end, 12), "CT-RETURN", "Return required; accounting period separately verified"),
    )


def small_company_ct_payment(period_end: date, *, instalments_excluded: bool):
    if instalments_excluded is not True:
        raise ValueError("Check instalment-payment applicability first.")
    return Obligation("ct_payment", add_months(period_end, 9) + timedelta(days=1), "CT-PAYMENT", "Non-instalment payment rule only")


def sa_deadlines(start_year: int):
    if type(start_year) is not int or not 2024 <= start_year <= 2026:
        raise ValueError("Only tax years starting 2024–2026 are researched here.")
    return (
        Obligation("sa_paper", date(start_year + 1, 10, 31), "SA-DEADLINES", "Ordinary deadline; notice-specific overrides may apply"),
        Obligation("sa_online", date(start_year + 2, 1, 31), "SA-DEADLINES", "Ordinary deadline; notice-specific overrides may apply"),
    )


def mtd_it_threshold(tax_year_start: int):
    """Threshold is strict 'over'; income is qualifying gross income, not profit."""
    return {2026: (2024, Decimal("50000")),
            2027: (2025, Decimal("30000")),
            2028: (2026, Decimal("20000"))}.get(tax_year_start)


def mtd_it_screen(tax_year_start: int, qualifying_income: Decimal, *, exemption: bool | None):
    if not isinstance(qualifying_income, Decimal) or not qualifying_income.is_finite() or qualifying_income < 0:
        raise ValueError("Use a non-negative finite Decimal for qualifying income.")
    if exemption is not None and type(exemption) is not bool:
        raise ValueError("Exemption status must be true, false or unknown.")
    threshold = mtd_it_threshold(tax_year_start)
    if threshold is None:
        return "outside_researched_years"
    if exemption is True:
        return "exempt_on_supplied_facts"
    if qualifying_income <= threshold[1]:
        return "threshold_not_exceeded_check_existing_mandation"
    if exemption is None:
        return "exemption_review_required"
    return "threshold_exceeded_verify_remaining_conditions"


def mtd_standard_updates(start_year: int):
    if start_year not in (2026, 2027, 2028):
        raise ValueError("Outside researched MTD rollout years.")
    start = date(start_year, 4, 6)
    ends = (date(start_year, 7, 5), date(start_year, 10, 5),
            date(start_year + 1, 1, 5), date(start_year + 1, 4, 5))
    dues = (date(start_year, 8, 7), date(start_year, 11, 7),
            date(start_year + 1, 2, 7), date(start_year + 1, 5, 7))
    return tuple({"start": start, "end": end, "due": due, "rule_id": "MTD-QUARTERS"}
                 for end, due in zip(ends, dues))


def micro_size_thresholds(period_start: date):
    """Nominal annual limits ONLY. Not a qualification decision.

    Two-year rules, transition, exclusions, groups and turnover prorating remain
    a separate qualification workflow. Do not use these as audit exemption.
    """
    if period_start < date(2016, 1, 1) or period_start > date(2026, 11, 5):
        raise ValueError("Period start outside researched window.")
    if period_start >= date(2025, 4, 6):
        return {"turnover": Decimal("1000000"), "assets": Decimal("500000"), "employees": 10}
    return {"turnover": Decimal("632000"), "assets": Decimal("316000"), "employees": 10}


def revised_accounts_requirements(*, original_start: date, original_end: date,
                                  replacement_start: date, replacement_end: date,
                                  original_approval: date | None, revision_approval: date | None,
                                  has_profit_loss: bool, has_revision_statements: bool):
    errors = []
    if original_start > original_end:
        errors.append("invalid_original_period")
    if (original_start, original_end) != (replacement_start, replacement_end):
        errors.append("original_period_must_be_preserved")
    if original_approval is None:
        errors.append("original_approval_required")
    elif original_approval < original_end:
        errors.append("original_approval_precedes_period_end")
    if revision_approval is None:
        errors.append("actual_revision_approval_required")
    elif original_approval and revision_approval < original_approval:
        errors.append("revision_precedes_original_approval")
    if has_profit_loss is not True:
        errors.append("replacement_profit_loss_required")
    if has_revision_statements is not True:
        errors.append("replacement_statements_required")
    return tuple(errors)
