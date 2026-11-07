"""Current job-backed expense recovery without monetary values or document bytes."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row

from .access import require_tenant
from .evidence_drafts_postgres import _require_draft_role
from .evidence_extraction_postgres import EvidenceNotEligible
from .job_csv_plans_postgres import _digest as _csv_digest
from .job_expense_effects_postgres import JobExpenseEffectReceipt
from .job_expense_plans_postgres import _digest as _expense_digest
from .job_tasks import ExpensePreparationPlan
from .postgres import _tenant_transaction


@dataclass(frozen=True)
class JobExpenseSummary:
    receipt: JobExpenseEffectReceipt
    plan: ExpensePreparationPlan
    expense_created_at: datetime
    organisation_id: UUID
    evidence_id: UUID
    content_sha256: str
    policy_version: str
    source_kind: str


def read_job_expense_summary(connection, actor, tenant_id, job_id, lease_token, csv_plan, expense_plan):
    require_tenant(actor, tenant_id, 'records:read')
    require_tenant(actor, tenant_id, 'records:write')
    tenant, job, lease = (UUID(str(value)) for value in (tenant_id, job_id, lease_token))
    with _tenant_transaction(connection, tenant, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'agent_job_expense_plans',
        'agent_job_csv_effects', 'agent_job_expense_effects', 'csv_extraction_results',
        'csv_clarification_answers', 'evidence_draft_amounts', 'csv_expense_drafts',
        'expense_accounting_periods', 'expense_account_policy',
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, 'read_job_expense_summary')
            cursor.execute('SELECT * FROM omnixat_extraction.read_job_expense_summary(%s,%s,%s,%s,%s)',
                           (job, actor.user_id, lease, _csv_digest(csv_plan), _expense_digest(expense_plan)))
            row = cursor.fetchone()
            if row is None or row['source_kind'] not in ('extracted', 'clarified'):
                raise EvidenceNotEligible('Job expense summary is unavailable')
            receipt = JobExpenseEffectReceipt(job, row['expense_id'], row['created_by'], row['created_at'])
            return JobExpenseSummary(receipt, expense_plan, row['expense_created_at'], row['organisation_id'],
                                     row['evidence_id'], row['content_sha256'].hex(), row['policy_version'], row['source_kind'])
