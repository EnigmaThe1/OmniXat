"""Tenant-scoped job checkpoints. Principals must come from trusted identity code.

Each call requires an exclusive idle autocommit connection. Payloads are hashed,
while progress contains bounded evidence references. Leases use the database clock.
"""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .access import require_tenant
from .job_tasks import EvidencePreparationTask
from .postgres import CreationConflict, TenantRecords, _tenant_transaction, validate_creation_key


@dataclass(frozen=True)
class JobCancellationReceipt:
    job_id: str
    cancelled_by: str = field(repr=False)
    cancelled_at: datetime


@dataclass(frozen=True)
class JobNoteReceipt:
    job_id: str
    note_id: UUID
    organisation_id: UUID
    created_by: str = field(repr=False)
    created_at: datetime


@dataclass(frozen=True)
class JobFailureReceipt:
    job_id: str
    worker_id: str = field(repr=False)
    failure_code: str
    will_retry: bool
    retry_at: datetime | None
    recorded_at: datetime


@dataclass(frozen=True)
class JobRetryState:
    attempt_limit: int
    attempts_started: int
    budget_started_at: datetime
    retry_at: datetime | None
    failure_code: str | None
    failed_at: datetime | None


@dataclass(frozen=True)
class ClaimedEvidenceTask:
    task: "EvidencePreparationTask"
    checkpoint: dict = field(repr=False)


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

    def create(self, actor, tenant, request_key, payload, *, max_attempts=3):
        scope = self._scope(actor, tenant, "records:write")
        self._validate_creation(request_key, max_attempts)
        with _tenant_transaction(self.connection, scope, write=True, tables_required=("agent_jobs",)):
            return self._insert_job(actor, scope, request_key, payload, max_attempts)[0]

    @staticmethod
    def _validate_creation(request_key, max_attempts):
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 200 or "\0" in request_key:
            raise ValueError("Bounded idempotency key required")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("Attempt limit must be between 1 and 20")

    def _insert_job(self, actor, scope, request_key, payload, max_attempts):
        """Internal insertion; caller owns the authorised write transaction."""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        digest = sha256(encoded).digest()
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                INSERT INTO omnixat.agent_jobs (tenant_id,request_key,payload_hash,created_by,attempt_limit)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,request_key) DO NOTHING RETURNING id
            """, (scope, request_key, digest, actor.user_id, max_attempts))
            inserted = cursor.fetchone() is not None
            cursor.execute("""
                SELECT id,payload_hash,attempt_limit FROM omnixat.agent_jobs WHERE tenant_id=%s AND request_key=%s
            """, (scope, request_key))
            row = cursor.fetchone()
            if row["payload_hash"] != digest or row["attempt_limit"] != max_attempts:
                raise ValueError("Idempotency key reused with different payload")
            return str(row["id"]), inserted

    def create_evidence_task(self, actor, tenant, request_key, task, *, max_attempts=3):
        """Persist reference-only inputs and the job atomically; no evidence is read."""
        scope = self._scope(actor, tenant, "records:write")
        require_tenant(actor, tenant, "records:read")
        self._validate_creation(request_key, max_attempts)
        if type(task) is not EvidencePreparationTask:
            raise ValueError("A validated evidence preparation task is required")
        with _tenant_transaction(self.connection, scope, write=True, tables_required=(
            "agent_jobs", "agent_job_evidence_tasks", "evidence_registrations",
        )):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT 1 FROM omnixat.evidence_registrations
                    WHERE tenant_id=%s AND organisation_id=%s AND id=%s AND content_sha256=%s
                """, (scope, task.organisation_id, task.evidence_id, task.content_sha256))
                if cursor.fetchone() is None:
                    raise KeyError("Evidence reference unavailable")
                job, inserted = self._insert_job(actor, scope, request_key, task.payload(), max_attempts)
                if inserted:
                    cursor.execute("""
                        INSERT INTO omnixat.agent_job_evidence_tasks
                            (tenant_id,job_id,organisation_id,evidence_id,content_sha256)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (scope, job, task.organisation_id, task.evidence_id, task.content_sha256))
                cursor.execute("""
                    SELECT organisation_id,evidence_id,content_sha256 FROM omnixat.agent_job_evidence_tasks
                    WHERE tenant_id=%s AND job_id=%s
                """, (scope, job))
                row = cursor.fetchone()
                if row is None or EvidencePreparationTask(**row) != task:
                    raise ValueError("Saved task specification unavailable or changed")
                return job

    def get_evidence_task(self, actor, tenant, job_id):
        """Recover immutable inputs only. Execution must use the evidence read gate."""
        scope = self._scope(actor, tenant, "records:read")
        job = UUID(str(job_id))
        with _tenant_transaction(self.connection, scope, tables_required=("agent_job_evidence_tasks",)):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT organisation_id,evidence_id,content_sha256 FROM omnixat.agent_job_evidence_tasks
                    WHERE tenant_id=%s AND job_id=%s
                """, (scope, job))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError("Task specification unavailable")
                return EvidencePreparationTask(**row)

    def save_expense_plan(self, actor, tenant, job_id, token, plan):
        from .job_expense_plans_postgres import save_expense_plan
        return save_expense_plan(self, actor, tenant, job_id, token, plan)

    def get_expense_plan(self, actor, tenant, job_id):
        from .job_expense_plans_postgres import get_expense_plan
        return get_expense_plan(self, actor, tenant, job_id)

    def save_csv_plan(self, actor, tenant, job_id, token, plan):
        from .job_csv_plans_postgres import save_csv_plan
        return save_csv_plan(self, actor, tenant, job_id, token, plan)

    def get_csv_plan(self, actor, tenant, job_id):
        from .job_csv_plans_postgres import get_csv_plan
        return get_csv_plan(self, actor, tenant, job_id)

    def get_claimed_evidence_task(self, actor, tenant, job_id, token) -> ClaimedEvidenceTask:
        """Read task/progress together only for the current live verified worker."""
        scope = self._scope(actor, tenant, "records:write")
        require_tenant(actor, tenant, "records:read")
        job, lease = UUID(str(job_id)), UUID(str(token))
        with _tenant_transaction(self.connection, scope, tables_required=("agent_jobs", "agent_job_evidence_tasks")):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT t.organisation_id,t.evidence_id,t.content_sha256,j.checkpoint
                    FROM omnixat.agent_jobs j JOIN omnixat.agent_job_evidence_tasks t
                      ON (t.tenant_id,t.job_id)=(j.tenant_id,j.id)
                    WHERE j.tenant_id=%s AND j.id=%s AND j.status='running'
                      AND j.claimed_by=%s AND j.lease_token=%s AND j.lease_until > clock_timestamp()
                """, (scope, job, actor.user_id, lease))
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("Claim expired, superseded or task unavailable")
                progress = row.pop("checkpoint")
                return ClaimedEvidenceTask(EvidencePreparationTask(**row), progress)

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
            self.connection.execute("""
                UPDATE omnixat.agent_jobs SET status='failed',failure_code='lease_exhausted',failed_at=clock_timestamp(),
                    lease_token=NULL,lease_until=NULL
                WHERE tenant_id=%s AND id=%s AND status='running' AND lease_until <= clock_timestamp()
                  AND attempts_started >= attempt_limit
            """, (scope, job))
            changed = self.connection.execute("""
                UPDATE omnixat.agent_jobs
                SET status='running',lease_token=%s,lease_until=clock_timestamp() + make_interval(secs => %s),claimed_by=%s,
                    attempts_started=attempts_started+1,retry_at=NULL
                WHERE tenant_id=%s AND id=%s
                  AND attempts_started < attempt_limit AND (retry_at IS NULL OR retry_at <= clock_timestamp())
                  AND (status='queued' OR (status='running' AND lease_until <= clock_timestamp()))
            """, (token, lease_seconds, actor.user_id, scope, job)).rowcount
        # Exhaustion is a durable terminal transition even when this claim fails.
        if changed != 1:
            raise ValueError("Job unavailable, delayed, exhausted or already claimed")
        return str(token)

    def checkpoint(self, actor, tenant, job_id, token, progress, *, complete=False, expected_progress=None):
        scope = self._scope(actor, tenant, "records:write")
        if not isinstance(progress, dict) or type(complete) is not bool:
            raise ValueError("Structured progress and explicit completion flag required")
        encoded = json.dumps(progress, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Checkpoint too large; store evidence references")
        expected = None
        if expected_progress is not None:
            if not isinstance(expected_progress, dict):
                raise ValueError("Structured expected progress required")
            expected_encoded = json.dumps(expected_progress, sort_keys=True, allow_nan=False)
            if len(expected_encoded.encode()) > 65536:
                raise ValueError("Expected checkpoint too large")
            expected = Jsonb(json.loads(expected_encoded))
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
                  AND (%s::jsonb IS NULL OR checkpoint=%s::jsonb)
            """, (Jsonb(json.loads(encoded)), "completed" if complete else "running", None if complete else lease,
                  complete, scope, job, actor.user_id, lease, expected, expected)).rowcount
            if changed != 1:
                raise ValueError("Claim expired, superseded, progress changed or job unavailable")


    def cancel(self, actor, tenant, job_id) -> JobCancellationReceipt:
        """Cancel queued or running preparation and replay the first attributed receipt."""
        scope = self._scope(actor, tenant, "records:write")
        job = UUID(str(job_id))
        with _tenant_transaction(self.connection, scope, write=True, tables_required=("agent_jobs",)):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT status,cancelled_by,cancelled_at FROM omnixat.agent_jobs
                    WHERE tenant_id=%s AND id=%s FOR UPDATE
                """, (scope, job))
                row = cursor.fetchone()
                if row is None or row["status"] in ("completed", "failed"):
                    raise ValueError("Job unavailable or already terminal")
                if row["status"] != "cancelled":
                    cursor.execute("""
                        UPDATE omnixat.agent_jobs SET status='cancelled',cancelled_by=%s,cancelled_at=clock_timestamp(),
                            lease_token=NULL,lease_until=NULL,retry_at=NULL WHERE tenant_id=%s AND id=%s
                        RETURNING cancelled_by,cancelled_at
                    """, (actor.user_id, scope, job))
                    row = cursor.fetchone()
                return JobCancellationReceipt(str(job), row["cancelled_by"], row["cancelled_at"])


    def create_note_effect(self, actor, tenant, job_id, token, operation_key, organisation_id, body) -> JobNoteReceipt:
        """Create or replay a note and its operation receipt under current job authority."""
        scope = self._scope(actor, tenant, "records:write")
        require_tenant(actor, tenant, "records:read")
        validate_creation_key(operation_key)
        if operation_key is None:
            raise ValueError("An explicit job operation key is required")
        job, lease, organisation = (UUID(str(value)) for value in (job_id, token, organisation_id))
        key_digest = sha256(operation_key.encode('ascii')).digest()
        payload_digest = sha256(json.dumps([1, str(organisation), body], separators=(',', ':'),
                                            allow_nan=False).encode('ascii')).digest()
        authority_query = """
            SELECT 1 FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s AND status='running'
              AND claimed_by=%s AND lease_token=%s AND lease_until > clock_timestamp()
        """
        authority = (scope, job, actor.user_id, lease)
        with _tenant_transaction(self.connection, scope, write=True, tables_required=(
            "tenants", "organisations", "notes", "record_creations", "agent_jobs", "agent_job_note_effects",
        )):
            records = TenantRecords(self.connection, actor, scope, True)
            try:
                with self.connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute("SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                   (scope, job))
                    cursor.fetchone()
                    cursor.execute(authority_query, authority)
                    if cursor.fetchone() is None:
                        raise ValueError("Claim expired, superseded or job unavailable")
                    cursor.execute("""
                        SELECT note_id,payload_digest,created_by,created_at FROM omnixat.agent_job_note_effects
                        WHERE tenant_id=%s AND job_id=%s AND key_digest=%s
                    """, (scope, job, key_digest))
                    previous = cursor.fetchone()
                    if previous is not None:
                        if previous["payload_digest"] != payload_digest:
                            raise CreationConflict("Job operation key does not match these note inputs")
                        note = records.get_note(previous["note_id"])
                        if (note["organisation_id"], note["body"], note["created_by"]) != (
                            organisation, body, previous["created_by"],
                        ):
                            raise CreationConflict("Saved job note no longer matches its receipt")
                    else:
                        note = records.create_note(organisation, body)
                        cursor.execute("""
                            INSERT INTO omnixat.agent_job_note_effects
                                (tenant_id,job_id,key_digest,payload_digest,note_id,created_by)
                            VALUES (%s,%s,%s,%s,%s,%s) RETURNING note_id,payload_digest,created_by,created_at
                        """, (scope, job, key_digest, payload_digest, note["id"], actor.user_id))
                        previous = cursor.fetchone()
                    cursor.execute(authority_query, authority)
                    if cursor.fetchone() is None:
                        raise ValueError("Claim expired, superseded or job unavailable")
                    return JobNoteReceipt(str(job), previous["note_id"], organisation,
                                          previous["created_by"], previous["created_at"])
            finally:
                records._active = False


    def retry_state(self, actor, tenant, job_id) -> JobRetryState:
        scope = self._scope(actor, tenant, "records:read")
        job = UUID(str(job_id))
        with _tenant_transaction(self.connection, scope, tables_required=("agent_jobs",)):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT attempt_limit,attempts_started,budget_started_at,retry_at,failure_code,failed_at
                    FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s
                """, (scope, job))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError("Job not found")
                return JobRetryState(**row)

    def fail(self, actor, tenant, job_id, token, failure_code, *, retryable, retry_after_seconds=60) -> JobFailureReceipt:
        """Record a fixed-code attempt outcome and release its claim atomically."""
        scope = self._scope(actor, tenant, "records:write")
        if type(failure_code) is not str or failure_code not in {
            "temporary_dependency", "invalid_input", "source_unavailable", "unexpected_error",
        }:
            raise ValueError("A supported failure code is required")
        if type(retryable) is not bool or type(retry_after_seconds) is not int or not 0 <= retry_after_seconds <= 86400:
            raise ValueError("Explicit retryability and a delay between 0 and 86400 seconds required")
        job, lease = UUID(str(job_id)), UUID(str(token))
        with _tenant_transaction(self.connection, scope, write=True, tables_required=("agent_jobs", "agent_job_failures")):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT id FROM omnixat.agent_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE", (scope, job))
                cursor.fetchone()
                cursor.execute("""
                    SELECT * FROM omnixat.agent_job_failures WHERE tenant_id=%s AND job_id=%s AND lease_token=%s
                """, (scope, job, lease))
                receipt = cursor.fetchone()
                if receipt is not None:
                    if (receipt["worker_id"], receipt["failure_code"], receipt["retryable"], receipt["retry_after_seconds"]) != (
                        actor.user_id, failure_code, retryable, retry_after_seconds,
                    ):
                        raise ValueError("Failure receipt does not match this attempt outcome")
                else:
                    cursor.execute("""
                        SELECT attempts_started,attempt_limit FROM omnixat.agent_jobs
                        WHERE tenant_id=%s AND id=%s AND status='running' AND claimed_by=%s AND lease_token=%s
                          AND lease_until > clock_timestamp()
                    """, (scope, job, actor.user_id, lease))
                    current = cursor.fetchone()
                    if current is None:
                        raise ValueError("Claim expired, superseded or job unavailable")
                    will_retry = retryable and current["attempts_started"] < current["attempt_limit"]
                    cursor.execute("""
                        UPDATE omnixat.agent_jobs SET status=%s,failure_code=%s,lease_token=NULL,lease_until=NULL,
                            claimed_by=CASE WHEN %s THEN NULL ELSE claimed_by END,
                            retry_at=CASE WHEN %s THEN clock_timestamp()+make_interval(secs => %s) ELSE NULL END,
                            failed_at=CASE WHEN %s THEN NULL ELSE clock_timestamp() END
                        WHERE tenant_id=%s AND id=%s AND lease_until > clock_timestamp() RETURNING retry_at
                    """, ("queued" if will_retry else "failed", failure_code, will_retry, will_retry,
                          retry_after_seconds, will_retry, scope, job))
                    updated = cursor.fetchone()
                    if updated is None:
                        raise ValueError("Claim expired, superseded or job unavailable")
                    retry_at = updated["retry_at"]
                    cursor.execute("""
                        INSERT INTO omnixat.agent_job_failures
                            (tenant_id,job_id,lease_token,worker_id,failure_code,retryable,retry_after_seconds,will_retry,retry_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                    """, (scope, job, lease, actor.user_id, failure_code, retryable, retry_after_seconds, will_retry, retry_at))
                    receipt = cursor.fetchone()
                return JobFailureReceipt(str(job), receipt["worker_id"], receipt["failure_code"], receipt["will_retry"],
                                         receipt["retry_at"], receipt["recorded_at"])
