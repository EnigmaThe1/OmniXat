"""Authorisation boundary for trusted server-side identity adapters.

Never build Principal from browser-supplied role or tenant headers. Membership,
revocation, MFA and API scopes must be verified by the identity adapter first.
"""
from dataclasses import dataclass


TENANT_PERMISSIONS = {
    "owner": frozenset({"records:read", "records:write", "filings:approve", "billing:manage", "members:manage"}),
    "editor": frozenset({"records:read", "records:write"}),
    "viewer": frozenset({"records:read"}),
}
STAFF_PERMISSIONS = {
    "platform_owner": frozenset({"metrics:read", "prices:write", "support:manage"}),
    "supervisor": frozenset({"metrics:read", "support:manage"}),
    "billing_admin": frozenset({"metrics:read", "prices:write"}),
    "support": frozenset({"support:manage"}),
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str | None
    tenant_role: str | None = None
    staff_role: str | None = None
    mfa_verified: bool = False
    # None is interactive access; an explicit set additionally restricts API calls.
    api_scopes: frozenset[str] | None = None
    # Verified by the identity adapter, never chosen by a model or API caller.
    actor_kind: str = "human"


def require_tenant(principal: Principal, tenant_id: str, permission: str):
    if principal.actor_kind not in ("human", "agent"):
        raise PermissionError("Unknown actor kind")
    if not principal.user_id or not tenant_id or principal.tenant_id != tenant_id:
        raise PermissionError("Access denied")
    if permission not in TENANT_PERMISSIONS.get(principal.tenant_role, ()):
        raise PermissionError("Access denied")
    if principal.api_scopes is not None and permission not in principal.api_scopes:
        raise PermissionError("Access denied")
    if principal.actor_kind == "agent" and permission in {"filings:approve", "billing:manage", "members:manage"}:
        raise PermissionError("Human decision required")
    if permission == "filings:approve" and not principal.mfa_verified:
        raise PermissionError("Step-up authentication required")


def require_staff(principal: Principal, permission: str):
    if principal.actor_kind != "human" or not principal.user_id or not principal.mfa_verified or principal.api_scopes is not None:
        raise PermissionError("Staff authentication required")
    if permission not in STAFF_PERMISSIONS.get(principal.staff_role, ()):
        raise PermissionError("Access denied")
