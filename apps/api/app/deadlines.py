"""Standard dates only. Never assert that an obligation exists unless explicitly configured."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

def obligation(kind: str, label: str, due: date, entity: str, basis: str, notes: str) -> dict:
    today = datetime.now(ZoneInfo('Europe/London')).date()
    if due < today:
        status = "date_passed_status_unknown"
    elif due <= today + timedelta(days=30):
        status = "upcoming"
    else:
        status = "scheduled"
    return {
        "kind": kind, "label": label, "due": due.isoformat(),
        "entity": entity, "basis": basis, "status": status, "notes": notes,
    }

def build_obligations(companies, tax_years, ct_periods) -> list[dict]:
    result: list[dict] = []
    by_company = {c.id: c for c in companies}
    for c in companies:
        if c.source != "companies_house":
            continue
        if c.accounts_due:
            result.append(obligation(
                "companies_house_accounts", "Companies House accounts", c.accounts_due,
                c.company_name, "companies_house_public_record",
                "Official public-register deadline; confirm whether already filed.",
            ))
        if c.confirmation_due:
            result.append(obligation(
                "confirmation_statement", "Confirmation statement", c.confirmation_due,
                c.company_name, "companies_house_public_record",
                "Official public-register deadline; confirm whether already filed.",
            ))
    for year in tax_years:
        if not year.self_assessment_required:
            continue
        result.append(obligation(
            "self_assessment_online", f"Self Assessment {year.start_year}–{str(year.start_year+1)[-2:]} online filing",
            date(year.start_year + 2, 1, 31), "Personal", "user_declared_standard_rule",
            "Standard online deadline. Confirm individual HMRC notice, MTD applicability and filing status.",
        ))
        if year.second_payment_expected:
            result.append(obligation(
                "second_payment_on_account", "Second Self Assessment payment on account",
                date(year.start_year + 2, 7, 31), "Personal", "user_declared_standard_rule",
                "Shown only because you said a second payment is expected; verify amount and deadline with HMRC.",
            ))
    for period in ct_periods:
        company = by_company.get(period.company_id)
        if company is None or not period.hmrc_return_required:
            continue
        result.append(obligation(
            "corporation_tax_payment", "Corporation Tax payment (usual deadline)",
            period.period_end + relativedelta(months=9, days=1),
            company.company_name, "user_declared_standard_rule",
            "Standard small-company rule; large-company instalments and special cases differ. Check HMRC.",
        ))
        result.append(obligation(
            "ct600_return", "Corporation Tax return CT600 (usual deadline)",
            period.period_end + relativedelta(months=12),
            company.company_name, "user_declared_standard_rule",
            "Standard rule based on user-entered HMRC accounting period; confirm notice, period and filing status.",
        ))
    return sorted(result, key=lambda item: (item["due"], item["entity"], item["kind"]))
