"""Execute one immutable plan through shared creators; never accept an amount."""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from psycopg.errors import InvalidParameterValue
from psycopg.rows import dict_row

from .access import require_tenant
from .evidence_drafts_postgres import _require_draft_role
from .job_csv_plans_postgres import _digest as _csv_digest
from .job_expense_plans_postgres import _digest as _expense_digest
from .postgres import _tenant_transaction


@dataclass(frozen=True)
class JobExpenseEffectReceipt:
    job_id: UUID
    expense_id: UUID
    created_by: str = field(repr=False)
    created_at: datetime


def execute_job_expense(connection, actor, tenant_id, job_id, lease_token, csv_plan, expense_plan):
    require_tenant(actor, tenant_id, 'records:read')
    require_tenant(actor, tenant_id, 'records:write')
    tenant, job, lease = (UUID(str(value)) for value in (tenant_id, job_id, lease_token))
    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'agent_job_expense_plans',
        'agent_job_csv_effects', 'agent_job_expense_effects', 'csv_extraction_results',
        'csv_clarification_answers', 'evidence_draft_amounts', 'csv_expense_drafts',
        'expense_accounting_periods', 'expense_account_policy',
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, 'create_job_expense_draft')
            try:
                cursor.execute('SELECT * FROM omnixat_extraction.create_job_expense_draft(%s,%s,%s,%s,%s)',
                               (job, actor.user_id, lease, _csv_digest(csv_plan), _expense_digest(expense_plan)))
            except InvalidParameterValue:
                raise ValueError('Expense source, policy, inputs or live worker claim unavailable') from None
            row = cursor.fetchone()
            return JobExpenseEffectReceipt(job, row['expense_id'], row['created_by'], row['created_at'])
