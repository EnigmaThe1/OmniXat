"""Tenant-scoped job checkpoints. Principals must come from trusted identity code.

Each call requires an exclusive idle autocommit connection. Payloads are hashed,
while progress contains bounded evidence references. Leases use the database clock.
"""
from hashlib import sha256
import json
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .access import require_tenant
from .postgres import _tenant_transaction


class PostgresJobStore:
    def __init__(self, connection):
        self.connection = connection

    def _scope(self, actor, tenant, permission):
        require_tenant(actor, tenant, permission)
        if actor.staff_role is not None:
            raise PermissionError("Tenant job access requires a tenant principal")
        if not isinstance(actor.user_id, str) or not actor.user_id.strip() or len(actor.user_id) > 200 or "\0" in actor.user_id:
            raise ValueError("Bounded job attribution required")
        return UUID(tenant)

    def create(self, actor, tenant, request_key, payload):
        scope = self._scope(actor, tenant, "records:write")
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 200 or "\0" in request_key:
            raise ValueError("Bounded idempotency key required")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        digest = sha256(encoded).digest()
        with _tenant_transaction(self.connection, scope, write=True, tables_required=("agent_jobs",)):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    INSERT INTO omnixat.agent_jobs (tenant_id,request_key,payload_hash,created_by)
                    VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id,request_key) DO NOTHING
                """, (scope, request_key, digest, actor.user_id))
                cursor.execute("""
                    SELECT id,payload_hash FROM omnixat.agent_jobs WHERE tenant_id=%s AND request_key=%s
                """, (scope, request_key))
                row = cursor.fetchone()
                if row["payload_hash"] != digest:
                    raise ValueError("Idempotency key reused with different payload")
                return str(row["id"])

    def get(self, actor, tenant, job_id):
        scope = self._scope(actor, tenant, "records:read")
        job = UUID(str(job_id))
        with _tenant_transaction(self.connection, scope, tables_required=("agent_jobs",)):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT id,status,checkpoint FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s",
                               (scope, job))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError("Job not found")
                return {"id": str(row["id"]), "status": row["status"], "checkpoint": row["checkpoint"]}

    def claim(self, actor, tenant, job_id, *, lease_seconds=60):
        scope = self._scope(actor, tenant, "records:write")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Lease must be between 1 and 3600 seconds")
        job, token = UUID(str(job_id)), uuid4()
        with _tenant_transaction(self.connection, scope, write=True, tables_required=("agent_jobs",)):
            # Acquire the row before checking the database clock. A lock wait
            # must not extend an expired claim or consume the new lease duration.
            self.connection.execute("SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (scope, job)).fetchone()
            changed = self.connection.execute("""
                UPDATE omnixat.agent_jobs
                SET status='running',lease_token=%s,lease_until=clock_timestamp() + make_interval(secs => %s),claimed_by=%s
                WHERE tenant_id=%s AND id=%s
                  AND (status='queued' OR (status='running' AND lease_until <= clock_timestamp()))
            """, (token, lease_seconds, actor.user_id, scope, job)).rowcount
            if changed != 1:
                raise ValueError("Job unavailable or already claimed")
        return str(token)

    def checkpoint(self, actor, tenant, job_id, token, progress, *, complete=False):
        scope = self._scope(actor, tenant, "records:write")
        if not isinstance(progress, dict) or type(complete) is not bool:
            raise ValueError("Structured progress and explicit completion flag required")
        encoded = json.dumps(progress, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Checkpoint too large; store evidence references")
        job, lease = UUID(str(job_id)), UUID(str(token))
        with _tenant_transaction(self.connection, scope, write=True, tables_required=("agent_jobs",)):
            # Acquire the row before checking the database clock. A lock wait
            # must not extend an expired claim or consume the new lease duration.
            self.connection.execute("SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (scope, job)).fetchone()
            changed = self.connection.execute("""
                UPDATE omnixat.agent_jobs SET checkpoint=%s,status=%s,lease_token=%s,
                    lease_until=CASE WHEN %s THEN NULL ELSE clock_timestamp() + interval '60 seconds' END
                WHERE tenant_id=%s AND id=%s AND status='running' AND claimed_by=%s
                  AND lease_token=%s AND lease_until > clock_timestamp()
            """, (Jsonb(json.loads(encoded)), "completed" if complete else "running", None if complete else lease,
                  complete, scope, job, actor.user_id, lease)).rowcount
            if changed != 1:
                raise ValueError("Claim expired, superseded or job unavailable")
