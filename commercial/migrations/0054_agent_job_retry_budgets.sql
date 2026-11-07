ALTER TABLE omnixat.agent_jobs
    ADD COLUMN attempt_limit integer NOT NULL DEFAULT 3 CHECK (attempt_limit BETWEEN 1 AND 20),
    ADD COLUMN attempts_started integer NOT NULL DEFAULT 0 CHECK (attempts_started BETWEEN 0 AND attempt_limit),
    ADD COLUMN budget_started_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    ADD COLUMN retry_at timestamptz,
    ADD COLUMN failure_code text CHECK (failure_code IN (
        'temporary_dependency', 'invalid_input', 'source_unavailable', 'unexpected_error', 'lease_exhausted'
    )),
    ADD COLUMN failed_at timestamptz,
    DROP CONSTRAINT agent_jobs_status_check,
    DROP CONSTRAINT agent_jobs_state_check,
    ADD CONSTRAINT agent_jobs_status_check CHECK (status IN ('queued', 'running', 'completed', 'cancelled', 'failed')),
    ADD CONSTRAINT agent_jobs_state_check CHECK (
        (status = 'queued' AND lease_token IS NULL AND lease_until IS NULL AND claimed_by IS NULL)
        OR (status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND claimed_by IS NOT NULL)
        OR (status IN ('completed', 'failed') AND lease_token IS NULL AND lease_until IS NULL AND claimed_by IS NOT NULL)
        OR (status = 'cancelled' AND lease_token IS NULL AND lease_until IS NULL)
    ),
    ADD CONSTRAINT agent_jobs_retry_check CHECK (retry_at IS NULL OR (status = 'queued' AND failure_code IS NOT NULL)),
    ADD CONSTRAINT agent_jobs_failure_check CHECK (
        (status = 'failed' AND failure_code IS NOT NULL AND failed_at IS NOT NULL)
        OR (status <> 'failed' AND failed_at IS NULL)
    );

CREATE TABLE omnixat.agent_job_failures (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    lease_token uuid NOT NULL,
    worker_id text NOT NULL CHECK (char_length(worker_id) BETWEEN 1 AND 200 AND btrim(worker_id) <> ''),
    failure_code text NOT NULL CHECK (failure_code IN (
        'temporary_dependency', 'invalid_input', 'source_unavailable', 'unexpected_error'
    )),
    retryable boolean NOT NULL,
    retry_after_seconds integer NOT NULL CHECK (retry_after_seconds BETWEEN 0 AND 86400),
    will_retry boolean NOT NULL,
    retry_at timestamptz,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, job_id, lease_token),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_jobs(tenant_id, id),
    CHECK ((will_retry AND retryable AND retry_at IS NOT NULL) OR (NOT will_retry AND retry_at IS NULL))
);
ALTER TABLE omnixat.agent_job_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_failures FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_failures
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_failures FROM PUBLIC;
