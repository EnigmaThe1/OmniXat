"""Signed bearer identity + persisted membership to shared record services.

Revocation/role changes take effect on the next unit of work. No principal cache,
self-enrolment, provider-role mapping or interactive filing-approval authority.
"""
from contextlib import contextmanager
from uuid import UUID

from psycopg.rows import dict_row

from .access import Principal, require_tenant
from .identity import AuthenticationError
from .postgres import _tenant_transaction, TenantRecords

RECORD_SCOPES = frozenset({'records:read', 'records:write'})


@contextmanager
def authenticated_records(connection, verifier, token, tenant_id, *, write=False):
    identity = verifier.verify(token)
    if type(write) is not bool:
        raise ValueError("Explicit write flag required")
    tenant = UUID(str(tenant_id))
    with _tenant_transaction(connection, tenant, write=write, identity_tables=True):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""SELECT set_config('omnixat.issuer', %s, true),
                                     set_config('omnixat.subject', %s, true)""",
                           (identity.issuer, identity.subject))
            cursor.execute("""SELECT i.id, i.actor_kind, m.role
                FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
                WHERE i.issuer=%s AND i.subject=%s AND m.tenant_id=%s
                    AND i.disabled_at IS NULL AND m.revoked_at IS NULL
                    AND %s > i.tokens_valid_after""",
                (identity.issuer, identity.subject, tenant, identity.issued_at))
            member = cursor.fetchone()
            if member is None:
                raise AuthenticationError("Workspace access denied")
        actor = Principal(str(member['id']), str(tenant), member['role'],
                          api_scopes=identity.scopes & RECORD_SCOPES,
                          actor_kind=member['actor_kind'])
        require_tenant(actor, str(tenant), 'records:write' if write else 'records:read')
        records = TenantRecords(connection, actor, tenant, write)
        try:
            yield records
        finally:
            records._active = False
