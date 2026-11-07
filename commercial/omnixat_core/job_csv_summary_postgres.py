"""Live-worker recovery metadata; no source bytes or monetary values are returned."""
from dataclasses import dataclass
from uuid import UUID

from psycopg.rows import dict_row

from .access import require_tenant
from .evidence_csv import AmountCell
from .evidence_extraction_postgres import EvidenceNotEligible, _require_extraction_role
from .evidence_review_postgres import CSVClarification, _QUESTIONS
from .job_csv_effects_postgres import JobCSVEffectReceipt
from .job_csv_plans_postgres import _digest
from .postgres import _tenant_transaction


@dataclass(frozen=True)
class JobCSVSummary:
    receipt: JobCSVEffectReceipt
    organisation_id: UUID
    evidence_id: UUID
    content_sha256: str
    policy_version: str
    found_count: int
    answered_count: int
    unavailable_count: int
    clarifications: tuple[CSVClarification, ...]


def _summary(job, plan, row):
    if row is None:
        raise EvidenceNotEligible('Job CSV summary is unavailable')
    states = row['cells']
    if not isinstance(states, list) or len(states) != len(plan.selections):
        raise EvidenceNotEligible('Job CSV summary is unavailable')
    found = answered = unavailable = 0
    questions = []
    for expected, state in zip(plan.selections, states):
        if (type(state) is not dict or set(state) != {
            'field_name', 'row', 'column', 'status', 'answered', 'unavailable',
        } or type(state['row']) is not int or type(state['column']) is not int
            or type(state['answered']) is not bool or type(state['unavailable']) is not bool):
            raise EvidenceNotEligible('Job CSV summary is unavailable')
        cell = AmountCell(state['field_name'], state['row'], state['column'])
        status = state['status']
        if (cell != expected or not isinstance(status, str) or status not in ('found', *_QUESTIONS)
            or (status == 'found' and state['answered']) or (state['unavailable'] and not state['answered'])):
            raise EvidenceNotEligible('Job CSV summary is unavailable')
        found += status == 'found'
        answered += state['answered']
        unavailable += state['unavailable']
        if status != 'found' and not state['answered']:
            questions.append(CSVClarification(cell, status, _QUESTIONS[status]))
    receipt = JobCSVEffectReceipt(job, row['stored_at'], row['created_by'], row['created_at'])
    return JobCSVSummary(receipt, row['organisation_id'], row['evidence_id'], row['content_sha256'].hex(),
                         row['policy_version'], found, answered, unavailable, tuple(questions))


def read_job_csv_summary(connection, actor, tenant_id, job_id, lease_token, plan):
    require_tenant(actor, tenant_id, 'records:read')
    require_tenant(actor, tenant_id, 'records:write')
    tenant, job, lease = (UUID(str(value)) for value in (tenant_id, job_id, lease_token))
    with _tenant_transaction(connection, tenant, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'agent_job_csv_effects',
        'csv_extraction_results', 'csv_clarification_answers',
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_extraction_role(cursor)
            cursor.execute("""SELECT
                has_function_privilege('omnixat_extraction.read_eligible_original(uuid,uuid)', 'EXECUTE')
                OR has_function_privilege('omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)', 'EXECUTE')
                OR has_function_privilege('omnixat_extraction.store_job_csv_result(uuid,text,uuid,uuid,bytea,text,bytea,jsonb)', 'EXECUTE')
                OR has_function_privilege('omnixat_extraction.read_csv_review(uuid,uuid,uuid)', 'EXECUTE')
                OR has_function_privilege('omnixat_extraction.read_csv_review_with_answers(uuid,uuid,uuid)', 'EXECUTE')
                OR has_function_privilege('omnixat_extraction.store_csv_answer(uuid,uuid,uuid,text,integer,integer,text,text)', 'EXECUTE')
                AS overprivileged""")
            if cursor.fetchone()['overprivileged']:
                raise PermissionError('Dedicated metadata-only summary grants required')
            cursor.execute('SELECT * FROM omnixat_extraction.read_job_csv_summary(%s,%s,%s,%s)',
                           (job, actor.user_id, lease, _digest(plan)))
            return _summary(job, plan, cursor.fetchone())
