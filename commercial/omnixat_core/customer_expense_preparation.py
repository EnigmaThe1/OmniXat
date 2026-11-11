"""Explicit bearer-authorised preparation; never constructs an approval principal."""
from datetime import date
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .evidence_drafts_postgres import _EXPENSE_POLICY_TABLES, _validate_cell
from .evidence_csv import AmountCell

_TABLES=(*_EXPENSE_POLICY_TABLES,'csv_expense_drafts','identities','memberships')


class PreparationActorChanged(Exception): pass
class PreparationConflict(Exception): pass


def _identity(verifier,token):
    identity=verifier.verify(token)
    if not {'records:read','records:write','evidence:read'} <= identity.scopes:
        raise PermissionError('Expense preparation scopes required')
    return identity


def _role(cursor):
    cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
        OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
        OR has_schema_privilege('omnixat_customer_preparation','CREATE') AS mixed""")
    if cursor.fetchone()['mixed']: raise PermissionError('Dedicated preparation grants required')


def expense_choices(connection,verifier,token,tenant,organisation,evidence):
    identity=_identity(verifier,token)
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    try:
        with _tenant_transaction(connection,tenant,tables_required=_TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor)
                cursor.execute('SELECT omnixat_customer_preparation.expense_choices(%s,%s,%s,%s,%s) AS choices',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence))
                choices=cursor.fetchone()['choices']
    except errors.InsufficientPrivilege: raise PermissionError('Preparation choices denied') from None
    if choices is None: raise KeyError('Preparation choices unavailable')
    return {**{key:choices[key][:20] for key in ('periods','accounts')},
        'has_more_periods':len(choices['periods'])>20,'has_more_accounts':len(choices['accounts'])>20}


def create_expense(connection,verifier,token,tenant,organisation,evidence,document,*,expected_actor):
    identity=_identity(verifier,token)
    if not isinstance(document,dict) or set(document)!={'job_id','field_name','row','column','period_id','expense_account_id','accounting_date'}:
        raise ValueError('Explicit source and accounting context required')
    cell=AmountCell(document['field_name'],document['row'],document['column']); _validate_cell(cell)
    for key in ('job_id','period_id','expense_account_id'):
        if not isinstance(document[key],str) or str(UUID(document[key]))!=document[key]:
            raise ValueError('Canonical preparation identifiers required')
    value=document['accounting_date']
    if not isinstance(value,str) or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:
        raise ValueError('Explicit ISO accounting date required')
    if expected_actor is None: raise ValueError('Initiating actor required')
    tenant,organisation,evidence,actor=(UUID(str(x)) for x in (tenant,organisation,evidence,expected_actor))
    try:
        with _tenant_transaction(connection,tenant,write=True,tables_required=_TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor)
                cursor.execute('SELECT * FROM omnixat_customer_preparation.create_expense(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,document['job_id'],actor,
                     cell.field_name,cell.row,cell.column,document['period_id'],document['expense_account_id'],date.fromisoformat(value)))
                row=cursor.fetchone()
    except errors.InsufficientPrivilege: raise PermissionError('Expense preparation denied') from None
    except errors.NoDataFound: raise PreparationActorChanged('Initiating actor changed') from None
    except errors.UniqueViolation: raise PreparationConflict('A different preparation is recorded') from None
    except errors.InvalidParameterValue: raise ValueError('Selected expense context or amount unavailable') from None
    except errors.CheckViolation: raise KeyError('Eligible resolved source required') from None
    return {'id':str(row['draft_id']),'created_at':row['stored_at'].isoformat()}
