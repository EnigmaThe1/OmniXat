from types import SimpleNamespace
from datetime import date
import pytest
import httpx
from pydantic import ValidationError
from app import companies_house
from app.schemas import CompanyInput, ManualCompanyInput

def test_company_number_normalised():
    assert CompanyInput(company_number="sc123456").company_number == "SC123456"
    with pytest.raises(ValidationError):
        CompanyInput(company_number="../hi!!!")

def test_blank_manual_company_name_rejected():
    with pytest.raises(ValidationError):
        ManualCompanyInput(company_number="12345678", company_name="    ")

def test_verified_company_parses_authoritative_deadlines(monkeypatch):
    monkeypatch.setattr(companies_house, "settings", SimpleNamespace(companies_house_key="test-only-key"))
    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "company_number":"01234567",
                "company_name":"EXAMPLE LTD",
                "company_status":"active",
                "accounts":{"next_accounts":{"due_on":"2027-09-30","period_end_on":"2026-12-31"}},
                "confirmation_statement":{"next_due":"2027-02-15"},
            }
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, **kwargs):
            assert url == "https://api.company-information.service.gov.uk/company/01234567"
            assert isinstance(kwargs["auth"], httpx.BasicAuth)
            return FakeResponse()
    monkeypatch.setattr(companies_house.httpx, "Client", FakeClient)
    profile = companies_house.fetch_profile("01234567")
    assert profile["accounts_due"] == date(2027, 9, 30)
    assert profile["confirmation_due"] == date(2027, 2, 15)
    assert profile["source"] == "companies_house"
