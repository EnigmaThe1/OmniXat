"""Read-only snapshot-bound bookkeeping history, without approval authority."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .expense_journal_postgres import _DRAFT_TABLES

TABLES=(*_DRAFT_TABLES,'expense_journal_review_decisions','identities','memberships')
FUNCTION='omnixat_customer_journal_reviews.read_observations(text,text,bigint,uuid,uuid,uuid,bytea,text)'

class JournalSnapshotChanged(Exception): pass


def read_observations(connection,verifier,token,tenant,organisation,evidence,draft,*,snapshot_sha256,after_reviewer=None):
    identity=verifier.verify(token)
    if not {'records:read','evidence:read'}<=identity.scopes: raise PermissionError('Review read scopes required')
    if not isinstance(snapshot_sha256,str) or len(snapshot_sha256)!=64 or any(c not in '0123456789abcdef' for c in snapshot_sha256):
        raise ValueError('Exact saved snapshot required')
    if after_reviewer is not None and (not isinstance(after_reviewer,str) or not 1<=len(after_reviewer)<=200
                                      or not after_reviewer.strip() or '\0' in after_reviewer):
        raise ValueError('Bounded reviewer cursor required')
    tenant,organisation,evidence,draft=(UUID(str(x)) for x in (tenant,organisation,evidence,draft))
    try:
        with _tenant_transaction(connection,tenant,tables_required=TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
                  OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
                  OR has_schema_privilege('omnixat_customer_journal_reviews','CREATE')
                  OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE n.nspname IN ('omnixat_customer_journals','omnixat_customer_journal_decisions') AND has_function_privilege(p.oid,'EXECUTE')) AS mixed""")
                if cursor.fetchone()['mixed']: raise PermissionError('Dedicated observation reader required')
                cursor.execute('SELECT omnixat_customer_journal_reviews.read_observations(%s,%s,%s,%s,%s,%s,%s,%s) AS result',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,draft,bytes.fromhex(snapshot_sha256),after_reviewer))
                result=cursor.fetchone()['result']
    except errors.InsufficientPrivilege: raise PermissionError('Observation inspection denied') from None
    except errors.NoDataFound: raise JournalSnapshotChanged('Saved snapshot changed') from None
    except errors.InvalidParameterValue: raise ValueError('Invalid observation page') from None
    if result is None: raise KeyError('Eligible saved journal required')
    rows=result['items'];items=rows[:20]
    return {'journal_id':result['journal_id'],'snapshot_sha256':result['snapshot_sha256'],'items':items,
            'has_more':len(rows)>20,'next_after_reviewer':items[-1]['reviewer_id'] if len(rows)>20 else None}
