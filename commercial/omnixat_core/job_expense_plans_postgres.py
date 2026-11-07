"""Immutable expense intent. This neither reads amounts nor creates an expense."""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from psycopg.rows import dict_row

from .access import require_tenant
from .expense_context import ExpenseDraftPolicy, validate_expense_context
from .job_tasks import ExpensePreparationPlan
from .job_csv_plans_postgres import _receipt as _csv_receipt
from .postgres import CreationConflict, _tenant_transaction


@dataclass(frozen=True)
class JobExpensePlanReceipt:
    job_id: str
    plan: ExpensePreparationPlan
    created_by: str = field(repr=False)
    created_at: datetime


def _digest(plan):
    return sha256(json.dumps([plan.format_version, plan.payload()], separators=(',', ':'), allow_nan=False).encode('ascii')).digest()


def _receipt(job, row):
    try:
        plan = ExpensePreparationPlan.from_payload({
            'source_cell': {'field_name': row['field_name'], 'row': row['source_row'], 'column': row['source_column']},
            'currency': row['currency'], 'accounting_date': row['accounting_date'].isoformat(),
            'expense_account_id': str(row['expense_account_id']), 'period_id': str(row['period_id']),
        })
        if row['format_version'] != plan.format_version or row['plan_digest'] != _digest(plan):
            raise ValueError('Invalid saved expense plan digest')
    except (ValueError, TypeError, KeyError):
        raise CreationConflict('Saved expense preparation plan is unavailable or changed') from None
    return JobExpensePlanReceipt(str(job), plan, row['created_by'], row['created_at'])


def save_expense_plan(store, actor, tenant, job_id, token, plan):
    scope = store._scope(actor, tenant, 'records:write')
    require_tenant(actor, tenant, 'records:read')
    if type(plan) is not ExpensePreparationPlan:
        raise ValueError('A validated expense preparation plan is required')
    job, lease = UUID(str(job_id)), UUID(str(token))
    authority_query = """SELECT 1 FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        AND status='running' AND claimed_by=%s AND lease_token=%s AND lease_until > clock_timestamp()"""
    authority = (scope, job, actor.user_id, lease)
    with _tenant_transaction(store.connection, scope, write=True, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'agent_job_expense_plans',
        'expense_accounting_periods', 'expense_account_policy',
    )):
        with store.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute('SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE', (scope, job))
            cursor.fetchone()
            cursor.execute(authority_query, authority)
            if cursor.fetchone() is None:
                raise ValueError('Claim expired, superseded or job unavailable')
            cursor.execute('SELECT * FROM omnixat.agent_job_csv_plans WHERE tenant_id=%s AND job_id=%s', (scope, job))
            row = cursor.fetchone()
            if row is None or plan.source_cell not in _csv_receipt(job, row).plan.selections:
                raise ValueError('Expense source must belong to the exact saved CSV plan')
            cursor.execute('SELECT organisation_id FROM omnixat.agent_job_evidence_tasks WHERE tenant_id=%s AND job_id=%s', (scope, job))
            organisation = cursor.fetchone()['organisation_id']
            cursor.execute("""SELECT p.starts_on,p.ends_on FROM omnixat.expense_accounting_periods p
                JOIN omnixat.expense_account_policy a USING (tenant_id,organisation_id)
                WHERE p.tenant_id=%s AND p.organisation_id=%s AND p.id=%s AND p.open_for_drafts
                  AND a.account_id=%s AND a.eligible_for_drafts""", (scope, organisation, plan.period_id, plan.context.expense_account_id))
            policy = cursor.fetchone()
            if policy is None:
                raise ValueError('Selected period or expense account is unavailable')
            validate_expense_context(scope, organisation, plan.context, ExpenseDraftPolicy(
                scope, organisation, policy['starts_on'], policy['ends_on'], frozenset({plan.context.expense_account_id})))
            cursor.execute("""INSERT INTO omnixat.agent_job_expense_plans
                (tenant_id,job_id,organisation_id,field_name,source_row,source_column,currency,
                 accounting_date,period_id,expense_account_id,plan_digest,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,job_id) DO NOTHING""", (
                    scope,job,organisation,plan.source_cell.field_name,plan.source_cell.row,plan.source_cell.column,
                    plan.context.currency,plan.context.accounting_date,plan.period_id,plan.context.expense_account_id,
                    _digest(plan),actor.user_id))
            cursor.execute('SELECT * FROM omnixat.agent_job_expense_plans WHERE tenant_id=%s AND job_id=%s', (scope, job))
            receipt = _receipt(job, cursor.fetchone())
            if receipt.plan != plan:
                raise CreationConflict('Job already has a different expense preparation plan')
            cursor.execute(authority_query, authority)
            if cursor.fetchone() is None:
                raise ValueError('Claim expired, superseded or job unavailable')
            return receipt


def get_expense_plan(store, actor, tenant, job_id):
    scope = store._scope(actor, tenant, 'records:read')
    job = UUID(str(job_id))
    with _tenant_transaction(store.connection, scope, tables_required=('agent_job_expense_plans',)):
        with store.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute('SELECT * FROM omnixat.agent_job_expense_plans WHERE tenant_id=%s AND job_id=%s', (scope, job))
            row = cursor.fetchone()
            if row is None:
                raise KeyError('Expense preparation plan unavailable')
            return _receipt(job, row)
