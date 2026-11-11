"""Structured requests and focused questions; never apply a correction or approve."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .customer_journal_observations import TABLES as OBSERVATION_TABLES, JournalSnapshotChanged
from .customer_bookkeeping_observations import ObservationActorChanged
from .journal_correction_questions import journal_correction_questions

TABLES=(*OBSERVATION_TABLES,'expense_journal_correction_requests','expense_journal_clarification_answers')
REASONS=('amount','account','funding','accounting_date','source_evidence')
FUNCTIONS={'read':'inspect(text,text,bigint,uuid,uuid,uuid,bytea,text)',
           'write':'record_reason(text,text,bigint,uuid,uuid,uuid,uuid,bytea,text)'}

class CorrectionReasonConflict(Exception): pass


def _role(cursor,operation):
    cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
      OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
      OR has_schema_privilege('omnixat_customer_corrections','CREATE')
      OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE (n.nspname IN ('omnixat_customer_journals','omnixat_customer_journal_reviews','omnixat_customer_journal_decisions')
          OR n.nspname='omnixat_customer_corrections' AND p.oid<>%s::regprocedure)
        AND has_function_privilege(p.oid,'EXECUTE')) AS mixed""",('omnixat_customer_corrections.'+FUNCTIONS[operation],))
    if cursor.fetchone()['mixed']: raise PermissionError('Dedicated correction capability required')


def _scope(verifier,token,tenant,organisation,evidence,draft,snapshot,write=False):
    identity=verifier.verify(token)
    required={'records:read','evidence:read'}|({'records:write'} if write else set())
    if not required<=identity.scopes: raise PermissionError('Correction scopes required')
    if not isinstance(snapshot,str) or len(snapshot)!=64 or any(c not in '0123456789abcdef' for c in snapshot):
        raise ValueError('Exact saved snapshot required')
    ids=tuple(UUID(str(x)) for x in (tenant,organisation,evidence,draft))
    return identity,ids,(identity.issuer,identity.subject,identity.issued_at,*ids[1:])


def read_corrections(connection,verifier,token,tenant,organisation,evidence,draft,*,snapshot_sha256,after_reviewer=None):
    identity,ids,params=_scope(verifier,token,tenant,organisation,evidence,draft,snapshot_sha256)
    if after_reviewer is not None and (not isinstance(after_reviewer,str) or not 1<=len(after_reviewer)<=200
                                      or not after_reviewer.strip() or '\0' in after_reviewer): raise ValueError('Invalid reviewer cursor')
    try:
        with _tenant_transaction(connection,ids[0],tables_required=TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor,'read')
                cursor.execute('SELECT omnixat_customer_corrections.inspect(%s,%s,%s,%s,%s,%s,%s,%s) AS result',params+(bytes.fromhex(snapshot_sha256),after_reviewer))
                result=cursor.fetchone()['result']
    except errors.InsufficientPrivilege: raise PermissionError('Correction inspection denied') from None
    except errors.SerializationFailure: raise JournalSnapshotChanged('Saved snapshot changed') from None
    if result is None: raise KeyError('Eligible saved journal required')
    rows=result['items'];result['items']=rows[:20];result['has_more']=len(rows)>20
    result['next_after_reviewer']=rows[19]['reviewer_id'] if len(rows)>20 else None
    own=result['own'];can_request=result.pop('can_request') and 'records:write' in identity.scopes
    result['choices']=list(REASONS) if can_request and own and own['decision']=='changes_requested' and own['reason'] is None else []
    result['questions']=[{'reason':q.reason,'question':q.question} for q in journal_correction_questions(
        row['correction_reason'] for row in rows[:20] if row['correction_reason'] and not row['clarification_recorded'])]
    return result


def record_reason(connection,verifier,token,tenant,organisation,evidence,draft,document,*,expected_actor):
    if not isinstance(document,dict) or set(document)!={'snapshot_sha256','reason'} or expected_actor is None:
        raise ValueError('Explicit snapshot, reason and actor required')
    reason=document['reason'];snapshot=document['snapshot_sha256']
    if reason not in REASONS: raise ValueError('Explicit correction reason required')
    identity,ids,params=_scope(verifier,token,tenant,organisation,evidence,draft,snapshot,True)
    actor=UUID(str(expected_actor))
    try:
        with _tenant_transaction(connection,ids[0],write=True,tables_required=TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                _role(cursor,'write')
                cursor.execute('SELECT * FROM omnixat_customer_corrections.record_reason(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    params+(actor,bytes.fromhex(snapshot),reason));result=cursor.fetchone()
    except errors.InsufficientPrivilege: raise PermissionError('Correction request denied') from None
    except errors.NoDataFound: raise ObservationActorChanged('Initiating actor changed') from None
    except errors.SerializationFailure: raise JournalSnapshotChanged('Saved snapshot changed') from None
    except errors.UniqueViolation: raise CorrectionReasonConflict('Different correction reason already recorded') from None
    except errors.CheckViolation: raise KeyError('Prior own changes-requested observation and eligible journal required') from None
    return {'journal_id':str(result['journal_id']),'snapshot_sha256':snapshot,'reason':reason,
            'reviewer_id':str(actor),'recorded_at':result['recorded_at'].isoformat()}
