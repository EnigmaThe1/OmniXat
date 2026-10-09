"""Private single-owner MVP: deadlines and public-register lookup only. NO filing."""
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import time
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from .database import Base, engine, get_db
from . import models
from .settings import settings
from .schemas import LoginInput, CompanyInput, ManualCompanyInput, PersonalYearInput, CorporationPeriodInput
from .companies_house import fetch_profile
from .deadlines import build_obligations

COOKIE = "omnixat_session"
MAX_AGE = 12 * 60 * 60
attempts: dict[str, list[float]] = defaultdict(list)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    # Milestone 0.1 only: replace create_all with Alembic migrations before financial data.
    Base.metadata.create_all(engine)
    yield

app = FastAPI(title="OmniXat Private API", version="0.1.0", lifespan=lifespan)
signer = URLSafeTimedSerializer(settings.session_secret or "invalid-for-production", salt="omnixat-owner-session")

def require_owner(request: Request):
    value = request.cookies.get(COOKIE)
    if not value:
        raise HTTPException(401, detail="Sign in to continue.")
    try:
        if signer.loads(value, max_age=MAX_AGE) != "owner":
            raise HTTPException(401, detail="Invalid session.")
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, detail="Session expired. Sign in again.")
    return True

def require_mutation_header(request: Request):
    if request.headers.get("X-OmniXat-Request") != "1":
        raise HTTPException(403, detail="Missing anti-CSRF request header.")

def add_audit(db: Session, name: str, target: str | None = None):
    db.add(models.AuditEvent(event_type=name, target_id=target))

def serial_company(c: models.Company) -> dict:
    return {
        "id": c.id, "company_number": c.company_number, "company_name": c.company_name,
        "company_status": c.company_status, "source": c.source,
        "accounts_due": c.accounts_due.isoformat() if c.accounts_due else None,
        "confirmation_due": c.confirmation_due.isoformat() if c.confirmation_due else None,
        "accounts_period_end": c.accounts_period_end.isoformat() if c.accounts_period_end else None,
        "checked_at": c.checked_at.isoformat() if c.checked_at else None,
    }

def public_status() -> dict:
    return {"companies_house_configured": bool(settings.companies_house_key), "filing_enabled": False}

@app.get("/health")
def health():
    return {"status": "ok", "service": "omnixat-api"}

@app.get("/api/session")
def session_state(request: Request):
    try:
        require_owner(request)
        authenticated = True
    except HTTPException:
        authenticated = False
    return {"authenticated": authenticated, **public_status()}

@app.post("/api/session", dependencies=[Depends(require_mutation_header)])
def login(body: LoginInput, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [x for x in attempts[ip] if now - x < 300]
    if len(recent) >= 5:
        raise HTTPException(429, detail="Too many attempts. Try again in five minutes.")
    left = hashlib.sha256(body.password.encode()).digest()
    right = hashlib.sha256(settings.owner_password.encode()).digest()
    if not hmac.compare_digest(left, right):
        attempts[ip] = recent + [now]
        raise HTTPException(401, detail="Incorrect password.")
    attempts.pop(ip, None)
    response.set_cookie(COOKIE, signer.dumps("owner"), max_age=MAX_AGE,
                        httponly=True, secure=settings.cookie_secure,
                        samesite="strict", path="/")
    return {"authenticated": True, **public_status()}

@app.delete("/api/session", dependencies=[Depends(require_mutation_header)])
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, samesite="strict")
    return {"authenticated": False}

@app.get("/api/overview", dependencies=[Depends(require_owner)])
def overview(db: Session = Depends(get_db)):
    companies = db.scalars(select(models.Company).order_by(models.Company.company_name)).all()
    years = db.scalars(select(models.PersonalTaxYear).order_by(models.PersonalTaxYear.start_year)).all()
    periods = db.scalars(select(models.CorporationTaxPeriod).order_by(models.CorporationTaxPeriod.period_end)).all()
    return {
        "companies": [serial_company(c) for c in companies],
        "tax_years": [{
            "start_year": y.start_year,
            "self_assessment_required": y.self_assessment_required,
            "second_payment_expected": y.second_payment_expected,
        } for y in years],
        "corporation_tax_periods": [{
            "id": p.id, "company_id": p.company_id, "period_end": p.period_end.isoformat(),
            "hmrc_return_required": p.hmrc_return_required,
        } for p in periods],
        "obligations": build_obligations(companies, years, periods),
        "capabilities": public_status(),
    }

def insert_company(db: Session, values: dict):
    existing = db.scalar(select(models.Company).where(models.Company.company_number == values["company_number"]))
    if existing:
        raise HTTPException(409, detail="Company already exists; use the refresh action if appropriate.")
    company = models.Company(**values)
    db.add(company)
    db.flush()
    add_audit(db, "company_added", company.id)
    db.commit()
    return serial_company(company)

@app.post("/api/companies/manual", dependencies=[Depends(require_owner), Depends(require_mutation_header)])
def add_manual(body: ManualCompanyInput, db: Session = Depends(get_db)):
    return insert_company(db, {
        "company_number": body.company_number,
        "company_name": body.company_name.strip(),
        "source": "manual_unverified",
    })

@app.post("/api/companies/import", dependencies=[Depends(require_owner), Depends(require_mutation_header)])
def import_company(body: CompanyInput, db: Session = Depends(get_db)):
    profile = fetch_profile(body.company_number)
    return insert_company(db, {**profile, "checked_at": datetime.now(timezone.utc)})

@app.post("/api/companies/{company_id}/refresh", dependencies=[Depends(require_owner), Depends(require_mutation_header)])
def refresh_company(company_id: str, db: Session = Depends(get_db)):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(404, detail="Company not found.")
    profile = fetch_profile(company.company_number)
    for k, v in profile.items():
        setattr(company, k, v)
    company.checked_at = datetime.now(timezone.utc)
    add_audit(db, "company_refreshed", company.id)
    db.commit()
    return serial_company(company)

@app.put("/api/personal-tax-years/{start_year}", dependencies=[Depends(require_owner), Depends(require_mutation_header)])
def upsert_personal_year(start_year: int, body: PersonalYearInput, db: Session = Depends(get_db)):
    if not 2000 <= start_year <= 2100:
        raise HTTPException(422, detail="Tax year outside supported range.")
    if body.second_payment_expected and not body.self_assessment_required:
        raise HTTPException(422, detail="A second payment on account requires Self Assessment applicability.")
    year = db.scalar(select(models.PersonalTaxYear).where(models.PersonalTaxYear.start_year == start_year))
    if year is None:
        year = models.PersonalTaxYear(start_year=start_year, self_assessment_required=body.self_assessment_required,
                                      second_payment_expected=body.second_payment_expected)
        db.add(year)
    else:
        year.self_assessment_required = body.self_assessment_required
        year.second_payment_expected = body.second_payment_expected
    db.flush()
    add_audit(db, "personal_tax_year_updated", year.id)
    db.commit()
    return {"start_year": year.start_year, "self_assessment_required": year.self_assessment_required,
            "second_payment_expected": year.second_payment_expected}

@app.post("/api/corporation-tax-periods", dependencies=[Depends(require_owner), Depends(require_mutation_header)])
def add_corporation_period(body: CorporationPeriodInput, db: Session = Depends(get_db)):
    if db.get(models.Company, body.company_id) is None:
        raise HTTPException(404, detail="Company not found.")
    if db.scalar(select(models.CorporationTaxPeriod).where(
        models.CorporationTaxPeriod.company_id == body.company_id,
        models.CorporationTaxPeriod.period_end == body.period_end,
    )):
        raise HTTPException(409, detail="This accounting period is already configured.")
    period = models.CorporationTaxPeriod(company_id=body.company_id, period_end=body.period_end,
                                         hmrc_return_required=body.hmrc_return_required)
    db.add(period)
    db.flush()
    add_audit(db, "corporation_tax_period_added", period.id)
    db.commit()
    return {"id": period.id, "company_id": period.company_id, "period_end": period.period_end.isoformat(),
            "hmrc_return_required": period.hmrc_return_required}
