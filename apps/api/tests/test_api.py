from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import Base, get_db

def test_protected_api_and_configured_year():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def temporary_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = temporary_db
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/api/overview").status_code == 401
            assert client.post("/api/session", json={"password":"wrong"}).status_code == 403
            assert client.post("/api/session", json={"password":"test-only-owner-password-12345"},
                               headers={"X-OmniXat-Request":"1"}).status_code == 200
            assert client.get("/api/overview").status_code == 200
            saved = client.put("/api/personal-tax-years/2025",
                json={"self_assessment_required": True, "second_payment_expected": False},
                headers={"X-OmniXat-Request":"1"})
            assert saved.status_code == 200
            overview = client.get("/api/overview").json()
            assert overview["obligations"][0]["due"] == "2027-01-31"
            assert overview["capabilities"]["filing_enabled"] is False
            assert client.delete("/api/session", headers={"X-OmniXat-Request":"1"}).status_code == 200
            assert client.get("/api/overview").status_code == 401
    finally:
        app.dependency_overrides.clear()

def test_manual_company_has_no_fabricated_deadline():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def temporary_db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = temporary_db
    try:
        with TestClient(app) as client:
            client.post("/api/session", json={"password":"test-only-owner-password-12345"},
                        headers={"X-OmniXat-Request":"1"})
            result = client.post("/api/companies/manual",
                json={"company_number":"12345678", "company_name":"Example Limited"},
                headers={"X-OmniXat-Request":"1"})
            assert result.status_code == 200
            assert result.json()["source"] == "manual_unverified"
            overview = client.get("/api/overview").json()
            assert overview["obligations"] == []
            assert overview["companies"][0]["accounts_due"] is None
            duplicate = client.post("/api/companies/manual",
                json={"company_number":"12345678","company_name":"Example Limited"},
                headers={"X-OmniXat-Request":"1"})
            assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.clear()
