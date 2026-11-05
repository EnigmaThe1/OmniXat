"""Read-only Companies House adapter. Never performs filing or changes company data."""
from datetime import date
import httpx
from fastapi import HTTPException
from .settings import settings

URL = "https://api.company-information.service.gov.uk"

def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None

def fetch_profile(number: str) -> dict:
    if not settings.companies_house_key:
        raise HTTPException(503, detail="Configure COMPANIES_HOUSE_API_KEY to retrieve an official company profile.")
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False) as client:
            response = client.get(
                f"{URL}/company/{number}",
                auth=httpx.BasicAuth(settings.companies_house_key, ""),
                headers={"Accept": "application/json"},
            )
        if response.status_code == 404:
            raise HTTPException(404, detail="Company not found at Companies House.")
        if response.status_code == 429:
            raise HTTPException(503, detail="Companies House rate limit reached. Try again later.")
        if response.status_code in (401, 403):
            raise HTTPException(503, detail="Companies House access was not authorised. Check your API key.")
        response.raise_for_status()
        data = response.json()
        accounts = data.get("accounts") or {}
        next_accounts = accounts.get("next_accounts") or {}
        confirmation = data.get("confirmation_statement") or {}
        return {
            "company_number": data["company_number"],
            "company_name": data["company_name"],
            "company_status": data.get("company_status"),
            "source": "companies_house",
            "accounts_due": parse_date(next_accounts.get("due_on")),
            "accounts_period_end": parse_date(next_accounts.get("period_end_on")),
            "confirmation_due": parse_date(confirmation.get("next_due")),
        }
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, detail="Unable to verify this company with Companies House right now.")
