"""Human customer preparation through separate capabilities; no approval authority."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .expense_journal_postgres import _DRAFT_TABLES, _journal_details, _journal_review_details

_TABLES=(*_DRAFT_TABLES,'identities','memberships')
FUNCTIONS={
    'inspect':'inspect(text,text,bigint,uuid,uuid,uuid)',
    'preview':'preview(text,text,bigint,uuid,uuid,uuid,uuid,uuid)',
    'create':'create_draft(text,text,bigint,uuid,uuid,uuid,uuid,uuid,bytea)',
}

class JournalActorChanged(Exception): pass
class JournalConflict(Exception): pass
class JournalPreviewChanged(Exception): pass


def _role(cursor,operation):
    cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
      OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
      OR has_schema_privilege('omnixat_customer_journals','CREATE')
      OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='omnixat_customer_journals' AND p.oid<>%s::regprocedure
          AND has_function_privilege(p.oid,'EXECUTE')) AS mixed""",
        ('omnixat_customer_journals.'+FUNCTIONS[operation],))
    if cursor.fetchone()['mixed']: raise PermissionError('Dedicated journal grants required')


def _native(row):
    row=dict(row)
    for key in ('expense_account_id','counterpart_account_id','funding_source_id','period_id','evidence_id','job_id','expense_draft_id','journal_id'):
        if key in row: row[key]=UUID(row[key])
    for key in ('content_sha256','snapshot_sha256'):
        if key in row: row[key]=bytes.fromhex(row[key][2:])
    row['accounting_date']=date.fromisoformat(row['accounting_date'])
    if 'journal_created_at' in row: row['journal_created_at']=datetime.fromisoformat(row['journal_created_at'])
    return row


def _serialize(preview):
    cell=preview.source_cell
    return {'draft_id':str(preview.draft_id),'funding_source_id':str(preview.funding_source_id),
        'currency':preview.currency,'accounting_date':preview.accounting_date.isoformat(),'period_id':str(preview.period_id),
        'lines':[{'account_id':str(line.account_id),'side':line.side,'amount_pence':str(line.amount_pence),
                  'amount':format(Decimal(line.amount_pence).scaleb(-2),'.2f')} for line in preview.lines],
        'source':{'evidence_id':str(preview.evidence_id),'job_id':str(preview.extraction_job_id),
          'field_name':cell.field_name,'row':cell.row,'column':cell.column,
          'policy_version':preview.scan_policy_version,'content_sha256':preview.content_sha256}}


def _call(connection,verifier,token,tenant,organisation,evidence,draft,operation,document=None,expected_actor=None):
    identity=verifier.verify(token)
    required={'records:read','evidence:read'}|({'records:write'} if operation!='inspect' else set())
    if not required<=identity.scopes: raise PermissionError('Journal scopes required')
    scope=tuple(UUID(str(x)) for x in (tenant,organisation,evidence,draft))
    params=(identity.issuer,identity.subject,identity.issued_at,*scope[1:])
    if operation!='inspect':
        keys={'counterpart_account_id'}|({'preview_sha256'} if operation=='create' else set())
        if not isinstance(document,dict) or set(document)!=keys or expected_actor is None:
            raise ValueError('Explicit counterpart, preview and actor required')
        account=document['counterpart_account_id']
        if not isinstance(account,str) or str(UUID(account))!=account or not UUID(account).int: raise ValueError('Invalid counterpart')
        params+= (UUID(str(expected_actor)),UUID(account))
        if operation=='create':
            digest=document['preview_sha256']
            if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest): raise ValueError('Invalid preview digest')
            params+=(bytes.fromhex(digest),)
    try:
        with _tenant_transaction(connection,scope[0],write=operation=='create',tables_required=_TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor,operation)
                name=FUNCTIONS[operation].split('(')[0]
                query=('SELECT * FROM ' if operation=='create' else 'SELECT ')+ 'omnixat_customer_journals.'+name+'('+','.join(['%s']*len(params))+')'
                if operation!='create': query+=' AS result'
                cursor.execute(query,params);row=cursor.fetchone()
    except errors.InsufficientPrivilege: raise PermissionError('Journal operation denied') from None
    except errors.NoDataFound: raise JournalActorChanged('Initiating actor changed') from None
    except errors.UniqueViolation: raise JournalConflict('Different journal already saved') from None
    except errors.SerializationFailure: raise JournalPreviewChanged('Preview changed') from None
    except errors.InvalidParameterValue: raise ValueError('Invalid journal preparation') from None
    except errors.CheckViolation: raise KeyError('Eligible expense and counterpart required') from None
    if operation=='create': return {'id':str(row['journal_id']),'draft_id':str(scope[3]),'created_at':row['created_at'].isoformat()}
    result=row['result']
    if result is None: raise KeyError('Eligible journal context required')
    if operation=='preview': return _serialize(_journal_details(_native(result),scope[3]))|{'preview_sha256':result['preview_sha256']}
    saved=result['journal']
    if saved:
        review=_journal_review_details(_native(saved))
        saved=_serialize(review.journal)|{'id':str(review.receipt.id),'created_at':review.receipt.created_at.isoformat(),
             'created_by':review.created_by,'snapshot_sha256':review.snapshot_sha256}
    choices=result['choices'] if 'records:write' in identity.scopes else []
    return {'journal':saved,'saved_unavailable':result['saved_unavailable'],'choices':choices[:20],'has_more':len(choices)>20}


def inspect_journal(connection,verifier,token,tenant,organisation,evidence,draft):
    return _call(connection,verifier,token,tenant,organisation,evidence,draft,'inspect')


def preview_journal(connection,verifier,token,tenant,organisation,evidence,draft,document,*,expected_actor):
    return _call(connection,verifier,token,tenant,organisation,evidence,draft,'preview',document,expected_actor)


def create_journal(connection,verifier,token,tenant,organisation,evidence,draft,document,*,expected_actor):
    return _call(connection,verifier,token,tenant,organisation,evidence,draft,'create',document,expected_actor)
