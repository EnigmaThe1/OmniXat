"""Explicit human bookkeeping observations; no posting or statutory approval."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .customer_journal_observations import TABLES, JournalSnapshotChanged

FUNCTION='omnixat_customer_journal_decisions.record_observation(text,text,bigint,uuid,uuid,uuid,uuid,bytea,text)'

class ObservationActorChanged(Exception): pass
class ObservationConflict(Exception): pass


def record_observation(connection,verifier,token,tenant,organisation,evidence,draft,document,*,expected_actor):
    identity=verifier.verify(token)
    if not {'records:read','records:write','evidence:read'}<=identity.scopes: raise PermissionError('Observation write scopes required')
    if not isinstance(document,dict) or set(document)!={'snapshot_sha256','decision'} or expected_actor is None:
        raise ValueError('Explicit saved snapshot, decision and actor required')
    digest=document['snapshot_sha256'];decision=document['decision']
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Exact saved snapshot required')
    if decision not in ('reviewed','changes_requested'): raise ValueError('Explicit bookkeeping observation required')
    tenant,organisation,evidence,draft,actor=(UUID(str(x)) for x in (tenant,organisation,evidence,draft,expected_actor))
    try:
        with _tenant_transaction(connection,tenant,write=True,tables_required=TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
                  OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
                  OR has_schema_privilege('omnixat_customer_journal_decisions','CREATE')
                  OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE n.nspname IN ('omnixat_customer_journals','omnixat_customer_journal_reviews')
                      AND has_function_privilege(p.oid,'EXECUTE')) AS mixed""")
                if cursor.fetchone()['mixed']: raise PermissionError('Dedicated observation writer required')
                cursor.execute('SELECT * FROM omnixat_customer_journal_decisions.record_observation(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,draft,actor,bytes.fromhex(digest),decision))
                result=cursor.fetchone()
    except errors.InsufficientPrivilege: raise PermissionError('Observation recording denied') from None
    except errors.NoDataFound: raise ObservationActorChanged('Initiating actor changed') from None
    except errors.SerializationFailure: raise JournalSnapshotChanged('Saved snapshot changed') from None
    except errors.UniqueViolation: raise ObservationConflict('Different observation already recorded') from None
    except errors.InvalidParameterValue: raise ValueError('Invalid observation') from None
    except errors.CheckViolation: raise KeyError('Eligible saved journal required') from None
    return {'journal_id':str(result['journal_id']),'snapshot_sha256':digest,'decision':decision,
            'reviewer_id':str(actor),'recorded_at':result['recorded_at'].isoformat()}
