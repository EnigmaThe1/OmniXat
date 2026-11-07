CREATE TABLE omnixat.agent_jobs (
    tenant_id uuid NOT NULL REFERENCES omnixat.tenants(id),
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    request_key text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 200 AND btrim(request_key) <> ''),
    payload_hash bytea NOT NULL CHECK (octet_length(payload_hash) = 32),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed')),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(checkpoint) = 'object' AND octet_length(checkpoint::text) <= 65536
    ),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    claimed_by text CHECK (char_length(claimed_by) BETWEEN 1 AND 200 AND btrim(claimed_by) <> ''),
    lease_token uuid,
    lease_until timestamptz,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, request_key),
    CHECK (
        (status = 'queued' AND lease_token IS NULL AND lease_until IS NULL AND claimed_by IS NULL)
        OR (status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND claimed_by IS NOT NULL)
        OR (status = 'completed' AND lease_token IS NULL AND lease_until IS NULL AND claimed_by IS NOT NULL)
    )
);

ALTER TABLE omnixat.agent_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_jobs
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_jobs FROM PUBLIC;
