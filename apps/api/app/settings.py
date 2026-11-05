import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("OMNIXAT_DATABASE_URL", "sqlite:///./omnixat-dev.db")
    session_secret: str = os.getenv("OMNIXAT_SESSION_SECRET", "")
    owner_password: str = os.getenv("OMNIXAT_OWNER_PASSWORD", "")
    companies_house_key: str = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    cookie_secure: bool = os.getenv("OMNIXAT_COOKIE_SECURE", "false").lower() == "true"

    def validate(self) -> None:
        if len(self.session_secret) < 32:
            raise RuntimeError("OMNIXAT_SESSION_SECRET must have at least 32 characters")
        if len(self.owner_password) < 16:
            raise RuntimeError("OMNIXAT_OWNER_PASSWORD must have at least 16 characters")

settings = Settings()
