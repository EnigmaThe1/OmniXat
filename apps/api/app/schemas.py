from datetime import date
from pydantic import BaseModel, Field, field_validator
import re

class LoginInput(BaseModel):
    password: str

class CompanyInput(BaseModel):
    company_number: str = Field(min_length=8, max_length=8)
    @field_validator("company_number")
    @classmethod
    def check_number(cls, v: str) -> str:
        value = v.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{8}", value):
            raise ValueError("Enter an eight-character UK company number")
        return value

class ManualCompanyInput(CompanyInput):
    company_name: str = Field(min_length=1, max_length=200)

class PersonalYearInput(BaseModel):
    self_assessment_required: bool
    second_payment_expected: bool = False

class CorporationPeriodInput(BaseModel):
    company_id: str = Field(min_length=36, max_length=36)
    period_end: date
    hmrc_return_required: bool
    @field_validator("period_end")
    @classmethod
    def check_date(cls, v: date) -> date:
        if not 2000 <= v.year <= 2100:
            raise ValueError("Period end outside supported date range")
        return v
