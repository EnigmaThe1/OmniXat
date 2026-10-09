from datetime import date
from types import SimpleNamespace
from app.deadlines import build_obligations

def test_self_assessment_2025_26_online_deadline():
    years = [SimpleNamespace(start_year=2025, self_assessment_required=True, second_payment_expected=False)]
    obligations = build_obligations([], years, [])
    assert len(obligations) == 1
    assert obligations[0]["due"] == "2027-01-31"
    assert obligations[0]["basis"] == "user_declared_standard_rule"

def test_second_payment_appears_only_if_declared():
    years = [SimpleNamespace(start_year=2025, self_assessment_required=True, second_payment_expected=True)]
    kinds = {o["kind"]: o["due"] for o in build_obligations([], years, [])}
    assert kinds == {"self_assessment_online": "2027-01-31", "second_payment_on_account": "2027-07-31"}

def test_no_obligations_are_invented_for_unknown_profile():
    assert build_obligations([], [], []) == []

def test_companies_house_only_uses_authoritative_dates():
    verified = SimpleNamespace(
        id="1", company_name="Test Ltd", source="companies_house",
        accounts_due=date(2027,9,30), confirmation_due=date(2027,3,7),
    )
    manual = SimpleNamespace(id="2", company_name="Unverified Ltd", source="manual_unverified",
                             accounts_due=None, confirmation_due=None)
    obs = build_obligations([verified, manual], [], [])
    assert {o["due"] for o in obs} == {"2027-09-30", "2027-03-07"}
    assert all(o["basis"] == "companies_house_public_record" for o in obs)

def test_corporation_tax_standard_deadlines_use_hmrc_period():
    company = SimpleNamespace(id="1", company_name="Example Ltd",
                              source="manual_unverified", accounts_due=None, confirmation_due=None)
    period = SimpleNamespace(company_id="1", period_end=date(2026,12,31), hmrc_return_required=True)
    dates = {o["kind"]: o["due"] for o in build_obligations([company], [], [period])}
    assert dates == {"corporation_tax_payment": "2027-10-01", "ct600_return": "2027-12-31"}

def test_corporation_tax_not_created_without_confirmed_obligation():
    company = SimpleNamespace(id="1", company_name="Example Ltd", source="manual_unverified",
                              accounts_due=None, confirmation_due=None)
    period = SimpleNamespace(company_id="1", period_end=date(2026,12,31), hmrc_return_required=False)
    assert build_obligations([company], [], [period]) == []
