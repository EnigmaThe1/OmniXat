"""Approval integrity only. There is deliberately no network submit function."""
from dataclasses import dataclass
from hashlib import sha256
from .access import Principal, require_tenant


@dataclass(frozen=True)
class Approval:
    tenant_id: str
    actor_id: str
    artifact_hash: str
    destination: str
    environment: str


def approve(actor: Principal, tenant_id: str, artifact: bytes, *, destination: str,
            environment: str) -> Approval:
    if actor.actor_kind != "human" or actor.api_scopes is not None:
        raise PermissionError("An interactive human must review and approve the filing")
    require_tenant(actor, tenant_id, "filings:approve")
    if destination not in ("companies_house", "hmrc") or environment not in ("sandbox", "live"):
        raise ValueError("Explicit supported destination and environment required")
    if not artifact:
        raise ValueError("Reviewable artifact required")
    return Approval(tenant_id, actor.user_id, sha256(artifact).hexdigest(), destination, environment)


def approval_matches(approval: Approval, tenant_id: str, artifact: bytes, *,
                     destination: str, environment: str) -> bool:
    return (approval.tenant_id == tenant_id and approval.destination == destination
            and approval.environment == environment
            and approval.artifact_hash == sha256(artifact).hexdigest())
