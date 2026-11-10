"""Explicit bearer-scoped clarification; never creates an approval principal."""
from uuid import UUID
from psycopg import errors
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .evidence_csv import AmountCell
from .evidence_review_postgres import validate_clarification, CSVClarificationConflict


class AnswerActorChanged(Exception):
    """The initiating actor must match the current verified identity."""


def answer_csv(connection,verifier,token,tenant,organisation,evidence,document,*,expected_actor):
    identity=verifier.verify(token)
    if not {'records:read','records:write','evidence:read','evidence:clarify'} <= identity.scopes:
        raise PermissionError('Clarification scopes required')
    if not isinstance(document,dict) or set(document)!={'job_id','field_name','row','column','amount'}:
        raise ValueError('Explicit clarification required')
    cell=AmountCell(document['field_name'],document['row'],document['column'])
    validate_clarification(cell,document['amount'])
    if not isinstance(document['job_id'],str) or str(UUID(document['job_id']))!=document['job_id']:
        raise ValueError('Canonical inspected job required')
    if expected_actor is None:
        raise ValueError('Initiating actor required')
    tenant,organisation,evidence,actor=(UUID(str(x)) for x in (tenant,organisation,evidence,expected_actor))
    try:
        with _tenant_transaction(connection,tenant,write=True,tables_required=(
                'identities','memberships','evidence_registrations','evidence_quarantine',
                'evidence_scan_verdicts','evidence_scan_claims','csv_extraction_results','csv_clarification_answers')):
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') OR has_schema_privilege('omnixat_extraction','USAGE,CREATE') OR has_schema_privilege('omnixat_customer_review','USAGE,CREATE') OR has_schema_privilege('omnixat_customer_answers','CREATE') AS direct_access")
                if cursor.fetchone()['direct_access']:
                    raise PermissionError('Separate answer-only grants required')
                cursor.execute('SELECT * FROM omnixat_customer_answers.answer_csv(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (identity.issuer,identity.subject,identity.issued_at,organisation,evidence,document['job_id'],actor,
                     cell.field_name,cell.row,cell.column,document['amount']))
                row=cursor.fetchone()
                if row is None or row['outcome']=='ineligible':
                    raise KeyError('Clarification unavailable')
                if row['outcome']=='conflict':
                    raise CSVClarificationConflict('A different answer is already recorded')
                if row['outcome']!='stored':
                    raise RuntimeError('Clarification receipt unavailable')
    except errors.InsufficientPrivilege:
        raise PermissionError('Clarification denied') from None
    except errors.NoDataFound:
        raise AnswerActorChanged('Initiating actor changed') from None
    return {'job_id':document['job_id'],'evidence_id':str(evidence),'field_name':cell.field_name,
            'row':cell.row,'column':cell.column,'answered_at':row['stored_at'].isoformat()}
