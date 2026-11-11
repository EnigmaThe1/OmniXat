"""Read-only customer inspection; bearer scopes never become approval authority."""
from uuid import UUID
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .evidence_drafts_postgres import _EXPENSE_POLICY_TABLES, _read_expense_draft
from .evidence_extraction_postgres import EvidenceNotEligible


def read_expense_drafts(connection,verifier,token,tenant,organisation,evidence,draft=None):
    identity=verifier.verify(token)
    if not {'records:read','evidence:read'} <= identity.scopes:
        raise PermissionError('Draft read scopes required')
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    draft=UUID(str(draft)) if draft is not None else None
    with _tenant_transaction(connection,tenant,tables_required=(*_EXPENSE_POLICY_TABLES,
            'csv_expense_drafts','identities','memberships')):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""SELECT has_schema_privilege('omnixat','USAGE,CREATE')
                OR has_schema_privilege('omnixat_extraction','USAGE,CREATE')
                OR has_schema_privilege('omnixat_customer_drafts','CREATE') AS direct_access""")
            if cursor.fetchone()['direct_access']:
                raise PermissionError('Dedicated draft reader required')
            cursor.execute('SELECT * FROM omnixat_customer_drafts.read_csv_expense_drafts(%s,%s,%s,%s,%s,%s)',
                (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,draft))
            rows=cursor.fetchall()
    if draft is not None and not rows:
        raise KeyError('No eligible expense draft')
    items=[]
    try:
        for row in rows[:20]:
            review=_read_expense_draft(row)
            source=review.source; cell=source.receipt.cell
            items.append({'id':str(review.receipt.id),'created_at':review.receipt.created_at.isoformat(),
                'created_by':review.created_by,'amount':str(source.amount),'currency':review.context.currency,
                'accounting_date':review.context.accounting_date.isoformat(),
                'expense_account_id':str(review.context.expense_account_id),'period_id':str(review.period_id),
                'source':{'evidence_id':str(source.receipt.evidence_id),'job_id':str(source.receipt.job_id),
                    'field_name':cell.field_name,'row':cell.row,'column':cell.column,
                    'kind':source.receipt.source_kind,'created_by':source.created_by,
                    'created_at':source.receipt.created_at.isoformat(),'policy_version':source.policy_version,
                    'content_sha256':source.content_sha256}})
    except EvidenceNotEligible:
        raise KeyError('No eligible expense draft') from None
    return {'items':items,'has_more':len(rows)>20}
