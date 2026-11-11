"""Customer funding context; separate read/write capabilities, no fund movement."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .expense_funding_postgres import _TABLES

_TABLES_REQUIRED=(*_TABLES,'identities','memberships')


class FundingActorChanged(Exception): pass
class FundingConflict(Exception): pass


def _identity(verifier,token,write=False):
    identity=verifier.verify(token)
    required={'records:read','evidence:read'}|({'records:write'} if write else set())
    if not required<=identity.scopes: raise PermissionError('Funding scopes required')
    return identity


def _role(cursor,write):
    opposite=('read_funding(text,text,bigint,uuid,uuid,uuid)' if write else
              'record_funding(text,text,bigint,uuid,uuid,uuid,uuid,uuid,uuid)')
    cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
        OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
        OR has_schema_privilege('omnixat_customer_funding','CREATE')
        OR has_function_privilege(%s,'EXECUTE') AS mixed""",('omnixat_customer_funding.'+opposite,))
    if cursor.fetchone()['mixed']: raise PermissionError('Dedicated funding grants required')


def read_funding(connection,verifier,token,tenant,organisation,evidence,draft):
    identity=_identity(verifier,token)
    tenant,organisation,evidence,draft=(UUID(str(x)) for x in (tenant,organisation,evidence,draft))
    try:
        with _tenant_transaction(connection,tenant,tables_required=_TABLES_REQUIRED):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor,False)
                cursor.execute('SELECT omnixat_customer_funding.read_funding(%s,%s,%s,%s,%s,%s) AS result',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,draft))
                result=cursor.fetchone()['result']
    except errors.InsufficientPrivilege: raise PermissionError('Funding inspection denied') from None
    if result is None: raise KeyError('Eligible expense draft required')
    choices=result['choices'] if 'records:write' in identity.scopes else []
    return {'funding':result['funding'],'choices':choices[:20],'has_more':len(choices)>20}


def record_funding(connection,verifier,token,tenant,organisation,evidence,draft,document,*,expected_actor):
    identity=_identity(verifier,token,True)
    if not isinstance(document,dict) or set(document)!={'funding_source_id','payer_id'} or expected_actor is None:
        raise ValueError('Explicit source/payer and initiating actor required')
    for value in document.values():
        if not isinstance(value,str) or str(UUID(value))!=value or not UUID(value).int:
            raise ValueError('Canonical nonzero funding identifiers required')
    tenant,organisation,evidence,draft,actor=(UUID(str(x)) for x in (tenant,organisation,evidence,draft,expected_actor))
    try:
        with _tenant_transaction(connection,tenant,write=True,tables_required=_TABLES_REQUIRED):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor,True)
                cursor.execute('SELECT * FROM omnixat_customer_funding.record_funding(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,draft,actor,
                     document['funding_source_id'],document['payer_id']))
                row=cursor.fetchone()
    except errors.InsufficientPrivilege: raise PermissionError('Funding selection denied') from None
    except errors.NoDataFound: raise FundingActorChanged('Initiating actor changed') from None
    except errors.UniqueViolation: raise FundingConflict('Different funding already recorded') from None
    except errors.InvalidParameterValue: raise ValueError('Explicit funding identifiers required') from None
    except errors.CheckViolation: raise KeyError('Eligible expense draft and funding choice required') from None
    return {'draft_id':str(draft),**document,'funding_kind':row['funding_kind'],'recorded_at':row['recorded_at'].isoformat()}
