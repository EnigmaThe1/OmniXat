"""Immutable proposed funding intent, bound to an exact job-backed expense."""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from psycopg.errors import InvalidParameterValue, UniqueViolation
from psycopg.rows import dict_row

from .access import require_tenant
from .evidence_drafts_postgres import _require_draft_role
from .job_csv_plans_postgres import _digest as _csv_digest
from .job_expense_plans_postgres import _digest as _expense_digest
from .job_tasks import JournalPreparationPlan
from .postgres import CreationConflict, _tenant_transaction


@dataclass(frozen=True)
class JobJournalPlanReceipt:
    job_id: UUID
    expense_id: UUID
    plan: JournalPreparationPlan
    created_by: str = field(repr=False)
    created_at: datetime


def _digest(plan):
    return sha256(json.dumps([plan.format_version, plan.payload()], separators=(',', ':'), allow_nan=False).encode('ascii')).digest()


def _receipt(job, row):
    try:
        plan = JournalPreparationPlan.from_payload({
            'funding_source_id': str(row['funding_source_id']), 'payer_id': str(row['payer_id']),
            'funding_kind': row['funding_kind'], 'counterpart_account_id': str(row['counterpart_account_id']),
        })
        if row['format_version'] != plan.format_version or row['plan_digest'] != _digest(plan):
            raise ValueError('Invalid saved journal plan digest')
    except (ValueError, TypeError, KeyError):
        raise CreationConflict('Saved journal preparation plan is unavailable or changed') from None
    return JobJournalPlanReceipt(job, row['expense_id'], plan, row['created_by'], row['created_at'])


def save_journal_plan(connection, actor, tenant_id, job_id, lease_token, csv_plan, expense_plan, plan):
    require_tenant(actor, tenant_id, 'records:read')
    require_tenant(actor, tenant_id, 'records:write')
    if type(plan) is not JournalPreparationPlan:
        raise ValueError('A validated journal preparation plan is required')
    tenant, job, lease = (UUID(str(value)) for value in (tenant_id, job_id, lease_token))
    with _tenant_transaction(connection, tenant, write=True, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'agent_job_expense_plans',
        'agent_job_csv_effects', 'agent_job_expense_effects', 'csv_extraction_results',
        'csv_clarification_answers', 'evidence_draft_amounts', 'csv_expense_drafts',
        'expense_accounting_periods', 'expense_account_policy', 'agent_job_journal_plans',
        'expense_funding_sources', 'expense_counterpart_policy',
    )):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_draft_role(cursor, 'save_job_journal_plan')
            try:
                cursor.execute('SELECT * FROM omnixat_extraction.save_job_journal_plan(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                               (job, actor.user_id, lease, _csv_digest(csv_plan), _expense_digest(expense_plan),
                                plan.funding_source_id, plan.payer_id, plan.funding_kind, plan.counterpart_account_id, _digest(plan)))
            except UniqueViolation:
                raise CreationConflict('Job already has different journal preparation intent') from None
            except InvalidParameterValue:
                raise ValueError('Job expense, funding mapping or live worker claim unavailable') from None
            receipt = _receipt(job, cursor.fetchone())
            if receipt.plan != plan:
                raise CreationConflict('Job journal preparation intent changed')
            return receipt


def get_journal_plan(store, actor, tenant_id, job_id):
    tenant = store._scope(actor, tenant_id, 'records:read')
    job = UUID(str(job_id))
    with _tenant_transaction(store.connection, tenant, tables_required=('agent_job_journal_plans',)):
        with store.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute('SELECT * FROM omnixat.agent_job_journal_plans WHERE tenant_id=%s AND job_id=%s', (tenant, job))
            row = cursor.fetchone()
            if row is None:
                raise KeyError('Journal preparation plan unavailable')
            return _receipt(job, row)
