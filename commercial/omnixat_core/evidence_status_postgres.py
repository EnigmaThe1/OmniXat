"""Metadata-only, fresh identity/member checked status; no payload capability."""
from uuid import UUID
from psycopg.rows import dict_row
from .postgres import _tenant_transaction


def read_scan_status(connection, verifier, token, tenant, organisation, evidence):
    identity=verifier.verify(token)
    if not {'records:read','evidence:read'} <= identity.scopes:
        raise PermissionError('Evidence read scope required')
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    with _tenant_transaction(connection,tenant,tables_required=(
            'identities','memberships','evidence_registrations','evidence_quarantine',
            'evidence_scan_verdicts','evidence_scan_claims')):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') AS direct_access")
            if cursor.fetchone()['direct_access']:
                raise PermissionError('Dedicated status grants required')
            cursor.execute('SELECT * FROM omnixat_evidence_status.read_status(%s,%s,%s,%s,%s)',
                           (identity.issuer,identity.subject,identity.issued_at,organisation,evidence))
            row=cursor.fetchone()
    if row is None:
        raise KeyError('Evidence status unavailable')
    return {key:value.isoformat() if hasattr(value,'isoformat') else str(value) if isinstance(value,UUID)
            else value for key,value in row.items()}
