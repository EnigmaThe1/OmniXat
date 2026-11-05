"""Versioned catalogue spike: in-memory persistence, no payment collection."""
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from .access import Principal, require_staff


@dataclass(frozen=True)
class PriceVersion:
    id: str
    plan: str
    amount_minor: int
    currency: str
    interval: str
    trial_days: int
    api_allowance: int
    effective_at: datetime


class PriceCatalogue:
    def __init__(self):
        self._versions = {}
        self._audit = []

    @property
    def audit(self):
        return tuple(self._audit)

    def create(self, actor: Principal, *, plan: str, amount_minor: int,
               interval: str, trial_days: int, api_allowance: int,
               effective_at: datetime) -> PriceVersion:
        require_staff(actor, "prices:write")
        if not isinstance(plan, str) or not plan.strip() or len(plan) > 80:
            raise ValueError("Plan name required")
        if interval not in ("month", "year"):
            raise ValueError("Unsupported interval")
        for value in (amount_minor, trial_days, api_allowance):
            if type(value) is not int or value < 0:
                raise ValueError("Use non-negative integer pricing values")
        if effective_at.tzinfo is None or effective_at.utcoffset() is None:
            raise ValueError("Timezone-aware effective date required")
        version = PriceVersion(str(uuid4()), plan.strip(), amount_minor, "GBP", interval,
                               trial_days, api_allowance, effective_at)
        self._versions[version.id] = version
        self._audit.append((actor.user_id, "price_version_created", version.id))
        return version

    def get(self, version_id: str):
        return self._versions[version_id]
