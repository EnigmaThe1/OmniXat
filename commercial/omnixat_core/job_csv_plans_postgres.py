"""Immutable CSV cell plans, pinned to an existing exact evidence task."""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .access import require_tenant
from .job_tasks import CSVExtractionPlan
from .postgres import CreationConflict, _tenant_transaction


@dataclass(frozen=True)
class JobCSVPlanReceipt:
    job_id: str
    plan: CSVExtractionPlan
    created_by: str = field(repr=False)
    created_at: datetime


def _digest(plan):
    return sha256(json.dumps([plan.format_version, plan.payload()], separators=(',', ':'), allow_nan=False).encode('ascii')).digest()


def _receipt(job, row):
    try:
        plan = CSVExtractionPlan.from_payload(row['selections'])
        if row['format_version'] != plan.format_version or row['plan_digest'] != _digest(plan):
            raise ValueError('Invalid saved plan digest')
    except (ValueError, TypeError, KeyError):
        raise CreationConflict('Saved CSV plan is unavailable or changed') from None
    return JobCSVPlanReceipt(str(job), plan, row['created_by'], row['created_at'])


def save_csv_plan(store, actor, tenant, job_id, token, plan) -> JobCSVPlanReceipt:
    scope = store._scope(actor, tenant, 'records:write')
    require_tenant(actor, tenant, 'records:read')
    if type(plan) is not CSVExtractionPlan:
        raise ValueError('A validated CSV extraction plan is required')
    job, lease = UUID(str(job_id)), UUID(str(token))
    authority_query = """SELECT 1 FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
        AND status='running' AND claimed_by=%s AND lease_token=%s AND lease_until > clock_timestamp()"""
    authority = (scope, job, actor.user_id, lease)
    with _tenant_transaction(store.connection, scope, write=True, tables_required=(
        'agent_jobs', 'agent_job_evidence_tasks', 'agent_job_csv_plans', 'evidence_registrations',
    )):
        with store.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute('SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE', (scope, job))
            cursor.fetchone()
            cursor.execute(authority_query, authority)
            if cursor.fetchone() is None:
                raise ValueError('Claim expired, superseded or job unavailable')
            cursor.execute("""SELECT 1 FROM omnixat.agent_job_evidence_tasks t
                JOIN omnixat.evidence_registrations r
                  ON (r.tenant_id,r.organisation_id,r.id,r.content_sha256)=
                     (t.tenant_id,t.organisation_id,t.evidence_id,t.content_sha256)
                WHERE t.tenant_id=%s AND t.job_id=%s AND r.media_type='text/csv'""", (scope, job))
            if cursor.fetchone() is None:
                raise ValueError('An exact CSV evidence task is required')
            cursor.execute("""INSERT INTO omnixat.agent_job_csv_plans
                (tenant_id,job_id,selections,plan_digest,created_by) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,job_id) DO NOTHING""", (scope, job, Jsonb(plan.payload()), _digest(plan), actor.user_id))
            cursor.execute('SELECT * FROM omnixat.agent_job_csv_plans WHERE tenant_id=%s AND job_id=%s', (scope, job))
            receipt = _receipt(job, cursor.fetchone())
            if receipt.plan != plan:
                raise CreationConflict('Job already has a different CSV extraction plan')
            cursor.execute(authority_query, authority)
            if cursor.fetchone() is None:
                raise ValueError('Claim expired, superseded or job unavailable')
            return receipt


def get_csv_plan(store, actor, tenant, job_id) -> JobCSVPlanReceipt:
    scope = store._scope(actor, tenant, 'records:read')
    job = UUID(str(job_id))
    with _tenant_transaction(store.connection, scope, tables_required=('agent_job_csv_plans',)):
        with store.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute('SELECT * FROM omnixat.agent_job_csv_plans WHERE tenant_id=%s AND job_id=%s', (scope, job))
            row = cursor.fetchone()
            if row is None:
                raise KeyError('CSV plan unavailable')
            return _receipt(job, row)
