"""Atomic pinned extraction effect. Only trusted worker code supplies results."""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg.errors import InvalidParameterValue

from .access import require_tenant
from .evidence_extraction_postgres import _require_extraction_role
from .job_csv_plans_postgres import _digest
from .postgres import _tenant_transaction


@dataclass(frozen=True)
class JobCSVEffectReceipt:
    job_id: UUID
    stored_at: datetime
    created_by: str = field(repr=False)
    created_at: datetime


def store_job_csv_effect(connection, actor, tenant_id, job_id, lease_token, plan, result):
    require_tenant(actor, tenant_id, 'records:write')
    require_tenant(actor, tenant_id, 'records:read')
    tenant, job, lease = (UUID(str(value)) for value in (tenant_id, job_id, lease_token))
    if tuple(value.cell for value in result.amounts) != plan.selections:
        raise ValueError('Result does not match saved plan')
    amounts = [{'field_name': value.cell.field_name, 'row': value.cell.row, 'column': value.cell.column,
                'status': value.status, 'amount': str(value.amount) if value.amount is not None else None}
               for value in result.amounts]
    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'agent_job_csv_effects',
        'csv_extraction_results',
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_extraction_role(cursor)
            try:
                cursor.execute('SELECT * FROM omnixat_extraction.store_job_csv_result(%s,%s,%s,%s,%s,%s,%s,%s)',
                               (job, actor.user_id, lease, result.evidence_id, _digest(plan), result.policy_version,
                                bytes.fromhex(result.content_sha256), Jsonb(amounts)))
            except InvalidParameterValue:
                raise ValueError('Extraction inputs, eligibility or live worker claim changed') from None
            row = cursor.fetchone()
            return JobCSVEffectReceipt(job, row['stored_at'], row['created_by'], row['created_at'])
