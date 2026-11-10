"""Durable human scan requests; separate execute-only database capability."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction


class ScanRequestUnavailable(Exception):
    """No current operator policy or complete, scoped upload."""


class ScanRequestActorChanged(Exception):
    """An optional initiating identity no longer matches."""


def request_scan(connection, verifier, token, tenant, organisation, evidence, *, expected_actor=None, cancel=False):
    if type(cancel) is not bool:
        raise ValueError('Explicit cancellation flag required')
    identity=verifier.verify(token)
    if not {'records:read','records:write','evidence:read','evidence:scan'} <= identity.scopes:
        raise PermissionError('Scan request scopes required')
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    expected_actor=UUID(str(expected_actor)) if expected_actor is not None else None
    try:
        with _tenant_transaction(connection,tenant,write=True,tables_required=(
                'identities','memberships','evidence_registrations','evidence_quarantine','evidence_scan_requests')):
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') AS direct_access")
                if cursor.fetchone()['direct_access']:
                    raise PermissionError('Dedicated scan request grants required')
                function='cancel_scan' if cancel else 'request_scan'
                cursor.execute('SELECT * FROM omnixat_evidence_requests.'+function+'(%s,%s,%s,%s,%s,%s)',
                               (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,expected_actor))
                row=cursor.fetchone()
                if row is None:
                    raise ScanRequestUnavailable('Scan request unavailable')
    except errors.InsufficientPrivilege:
        raise PermissionError('Scan request denied') from None
    except errors.NoDataFound:
        raise ScanRequestActorChanged('Scan request actor changed') from None
    return {key:value.isoformat() if hasattr(value,'isoformat') else str(value) if isinstance(value,UUID)
            else value for key,value in row.items()}
