ALTER TABLE omnixat.agent_jobs
    ADD COLUMN cancelled_by text CHECK (
        char_length(cancelled_by) BETWEEN 1 AND 200 AND btrim(cancelled_by) <> ''
    ),
    ADD COLUMN cancelled_at timestamptz,
    DROP CONSTRAINT agent_jobs_status_check,
    DROP CONSTRAINT agent_jobs_check,
    ADD CONSTRAINT agent_jobs_status_check CHECK (status IN ('queued', 'running', 'completed', 'cancelled')),
    ADD CONSTRAINT agent_jobs_state_check CHECK (
        (status = 'queued' AND lease_token IS NULL AND lease_until IS NULL AND claimed_by IS NULL)
        OR (status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND claimed_by IS NOT NULL)
        OR (status = 'completed' AND lease_token IS NULL AND lease_until IS NULL AND claimed_by IS NOT NULL)
        OR (status = 'cancelled' AND lease_token IS NULL AND lease_until IS NULL)
    ),
    ADD CONSTRAINT agent_jobs_cancellation_check CHECK (
        (status = 'cancelled' AND cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL)
        OR (status <> 'cancelled' AND cancelled_by IS NULL AND cancelled_at IS NULL)
    );
