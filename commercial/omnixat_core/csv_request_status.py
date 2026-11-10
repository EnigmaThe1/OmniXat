"""Read-only, bounded historical request receipts; no originals or result values."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .csv_extraction_plan import validate_extraction_plan
from .csv_requests_postgres import _TABLES_REQUIRED, cell_documents
from .postgres import _tenant_transaction


def read_requests(connection,verifier,token,tenant,organisation,evidence,job=None):
    identity=verifier.verify(token)
    if not {'records:read','evidence:read'} <= identity.scopes:
        raise PermissionError('Request inspection scopes required')
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    job=UUID(str(job)) if job is not None else None
    try:
        with _tenant_transaction(connection,tenant,tables_required=_TABLES_REQUIRED):
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') OR has_schema_privilege('omnixat_extraction','USAGE,CREATE') OR has_schema_privilege('omnixat_csv_requests','USAGE,CREATE') OR has_schema_privilege('omnixat_csv_request_status','CREATE') AS mixed")
                if cursor.fetchone()['mixed']: raise PermissionError('Separate request-reader grants required')
                cursor.execute('SELECT * FROM omnixat_csv_request_status.read_requests(%s,%s,%s,%s,%s,%s)',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,job))
                rows=cursor.fetchall()
    except errors.InsufficientPrivilege:
        raise PermissionError('Request inspection denied') from None
    if job is not None and not rows: raise KeyError('Request unavailable')
    items=[]
    for row in rows[:20]:
        try:
            *_,selections=validate_extraction_plan({'tenant':str(tenant),'organisation':str(organisation),
                'evidence':str(evidence),'job':str(row['job_id']),'selections':row['selections']})
        except (ValueError,TypeError): raise KeyError('Request inspection unavailable') from None
        if row['state'] not in {'awaiting_worker','cancelled','result_recorded'}:
            raise KeyError('Request inspection unavailable')
        items.append({key:value.isoformat() if hasattr(value,'isoformat') else str(value) if isinstance(value,UUID)
            else value for key,value in row.items()}|{'selections':cell_documents(selections)})
    return {'items':items,'has_more':len(rows)>20}
