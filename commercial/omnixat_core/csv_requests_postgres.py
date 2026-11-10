"""Durable coordinate requests and explicit, freshly authorised worker effects."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .csv_extraction_plan import validate_extraction_plan
from .evidence_extraction_postgres import (
    _TABLES, _require_extraction_role, _amount_documents, extract_csv_amounts,
    CSVExtractionReceipt, CSVExtractionConflict, EvidenceNotEligible,
)
from .postgres import _tenant_transaction

_TABLES_REQUIRED=(*_TABLES,'identities','memberships','csv_extraction_requests','csv_extraction_results')


class RequestActorChanged(Exception):
    """Initiating actor continuity failed."""


def cell_documents(selections):
    return [{'field_name':v.field_name,'row':v.row,'column':v.column} for v in selections]


def request_csv(connection,verifier,token,tenant,organisation,evidence,document,*,expected_actor):
    identity=verifier.verify(token)
    if not {'records:read','records:write','evidence:read','evidence:extract'} <= identity.scopes:
        raise PermissionError('Extraction request scopes required')
    if not isinstance(document,dict) or set(document)!={'job_id','selections'} or expected_actor is None:
        raise ValueError('Explicit request and initiating actor required')
    tenant,organisation,evidence,job,selections=validate_extraction_plan({
        'tenant':str(tenant),'organisation':str(organisation),'evidence':str(evidence),
        'job':document['job_id'],'selections':document['selections']})
    try:
        with _tenant_transaction(connection,UUID(tenant),write=True,tables_required=_TABLES_REQUIRED):
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') OR has_schema_privilege('omnixat_extraction','USAGE,CREATE') OR has_schema_privilege('omnixat_csv_requests','CREATE') OR has_function_privilege('omnixat_csv_requests.worker_request(uuid,uuid,uuid,jsonb)','EXECUTE') OR has_function_privilege('omnixat_csv_requests.store_requested_result(uuid,uuid,uuid,jsonb,text,bytea,jsonb)','EXECUTE') AS overprivileged")
                if cursor.fetchone()['overprivileged']:
                    raise PermissionError('Request-only capability required')
                cursor.execute('SELECT * FROM omnixat_csv_requests.request_csv(%s,%s,%s,%s,%s,%s,%s,%s)',
                    (identity.issuer,identity.subject,identity.issued_at,UUID(organisation),UUID(evidence),UUID(job),
                     UUID(str(expected_actor)),Jsonb(cell_documents(selections))))
                row=cursor.fetchone()
                if row is None: raise KeyError('No eligible CSV source')
    except errors.InsufficientPrivilege:
        raise PermissionError('Extraction request denied') from None
    except errors.NoDataFound:
        raise RequestActorChanged('Initiating actor changed') from None
    except errors.UniqueViolation:
        raise CSVExtractionConflict('Request job already has another plan') from None
    return {'job_id':str(row['job_id']),'policy_version':row['policy_version'],'requested_at':row['requested_at'].isoformat()}


def _require_requested_worker(cursor):
    _require_extraction_role(cursor)
    cursor.execute("""SELECT has_function_privilege('omnixat_csv_requests.request_csv(text,text,bigint,uuid,uuid,uuid,uuid,jsonb)','EXECUTE')
        OR has_function_privilege('omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)','EXECUTE')
        OR has_schema_privilege('omnixat_csv_requests','CREATE') AS mixed""")
    if cursor.fetchone()['mixed']:
        raise PermissionError('Separate requested-worker grants required')


def extract_requested_csv(connection,tenant,organisation,evidence,job,selections):
    # Apply the same bounded canonical plan contract before a worker reads an original.
    tenant,organisation,evidence,job,selections=validate_extraction_plan({
        'tenant':str(tenant),'organisation':str(organisation),'evidence':str(evidence),'job':str(job),
        'selections':cell_documents(selections)})
    cells=Jsonb(cell_documents(selections))
    with _tenant_transaction(connection,UUID(tenant),tables_required=_TABLES_REQUIRED):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_requested_worker(cursor)
            cursor.execute('SELECT * FROM omnixat_csv_requests.worker_request(%s,%s,%s,%s)',
                (UUID(organisation),UUID(evidence),UUID(job),cells))
            admitted=cursor.fetchone()
            if admitted is None: raise EvidenceNotEligible('Requested extraction unavailable')
    result=extract_csv_amounts(connection,tenant,organisation,evidence,selections)
    if (result.policy_version,result.content_sha256)!=(admitted['policy_version'],admitted['content_sha256'].hex()):
        raise EvidenceNotEligible('Requested source changed')
    with _tenant_transaction(connection,UUID(tenant),write=True,tables_required=_TABLES_REQUIRED):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_requested_worker(cursor)
            cursor.execute('SELECT * FROM omnixat_csv_requests.store_requested_result(%s,%s,%s,%s,%s,%s,%s)',
                (UUID(organisation),UUID(evidence),UUID(job),cells,result.policy_version,
                 bytes.fromhex(result.content_sha256),Jsonb(_amount_documents(result))))
            row=cursor.fetchone()
            if row is None or row['outcome']=='ineligible': raise EvidenceNotEligible('Requested extraction unavailable')
            if row['outcome']=='conflict': raise CSVExtractionConflict('Request result conflicts')
            if row['outcome']!='stored': raise RuntimeError('Request receipt unavailable')
    return CSVExtractionReceipt(UUID(job),UUID(evidence),row['stored_at'])
