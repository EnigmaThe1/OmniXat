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


def new_price_version(*, plan, amount_minor, interval, trial_days, api_allowance, effective_at):
    if not isinstance(plan, str) or not plan.strip() or len(plan) > 80:
        raise ValueError("Plan name required")
    if interval not in ("month", "year"):
        raise ValueError("Unsupported interval")
    for value, maximum in ((amount_minor, 2**63-1), (trial_days, 2**31-1), (api_allowance, 2**63-1)):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError("Use non-negative integer pricing values")
    if not isinstance(effective_at, datetime) or effective_at.utcoffset() is None:
        raise ValueError("Timezone-aware effective date required")
    return PriceVersion(str(uuid4()), plan.strip(), amount_minor, "GBP", interval,
                           trial_days, api_allowance, effective_at)


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
        version = new_price_version(plan=plan, amount_minor=amount_minor, interval=interval,
                                    trial_days=trial_days, api_allowance=api_allowance,
                                    effective_at=effective_at)
        self._versions[version.id] = version
        self._audit.append((actor.user_id, "price_version_created", version.id))
        return version

    def get(self, version_id: str):
        return self._versions[version_id]
