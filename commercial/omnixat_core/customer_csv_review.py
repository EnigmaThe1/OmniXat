"""Bearer-scoped read-only candidate inspection, with shared review validation."""
from uuid import UUID
from psycopg.rows import dict_row
from .postgres import _tenant_transaction
from .evidence_review_postgres import _decode_amounts, _decode_answers, CSVExtractionReview
from .evidence_extraction_postgres import EvidenceNotEligible


def read_latest_csv(connection,verifier,token,tenant,organisation,evidence):
    identity=verifier.verify(token)
    if not {'records:read','evidence:read'} <= identity.scopes:
        raise PermissionError('Evidence read scopes required')
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    with _tenant_transaction(connection,tenant,tables_required=('identities','memberships',
            'evidence_registrations','evidence_quarantine','evidence_scan_verdicts','evidence_scan_claims',
            'csv_extraction_results','csv_clarification_answers')):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') OR has_schema_privilege('omnixat_extraction','USAGE,CREATE') AS direct_access")
            if cursor.fetchone()['direct_access']:
                raise PermissionError('Dedicated candidate reader required')
            cursor.execute('SELECT * FROM omnixat_customer_review.read_latest_csv(%s,%s,%s,%s,%s)',
                           (identity.issuer,identity.subject,identity.issued_at,organisation,evidence))
            row=cursor.fetchone()
    if row is None:
        raise KeyError('No eligible CSV candidates')
    try:
        amounts=_decode_amounts(row['amounts'])
        answers=_decode_answers(row['answers'],amounts)
    except EvidenceNotEligible:
        raise KeyError('No eligible CSV candidates') from None
    review=CSVExtractionReview(row['job_id'],evidence,row['policy_version'],row['extractor_version'],
        row['content_sha256'].hex(),row['stored_at'],amounts,answers)
    def cell(value):
        return {'field_name':value.field_name,'row':value.row,'column':value.column}
    return {'job_id':str(review.job_id),'evidence_id':str(evidence),'policy_version':review.policy_version,
        'extractor_version':review.extractor_version,'content_sha256':review.content_sha256,
        'stored_at':review.stored_at.isoformat(),
        'amounts':[cell(v.cell)|{'status':v.status,'amount':str(v.amount) if v.amount is not None else None} for v in amounts],
        'answers':[cell(v.cell)|{'amount':str(v.amount) if v.amount is not None else None,
                    'answered_by':v.answered_by,'answered_at':v.answered_at.isoformat()} for v in answers],
        'questions':[cell(v.cell)|{'reason':v.reason,'question':v.question} for v in review.clarifications]}
