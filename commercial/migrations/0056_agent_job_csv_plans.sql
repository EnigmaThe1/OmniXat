CREATE TABLE omnixat.agent_job_csv_plans (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    format_version integer NOT NULL DEFAULT 1 CHECK (format_version = 1),
    selections jsonb NOT NULL CHECK (
        jsonb_typeof(selections) = 'array' AND jsonb_array_length(selections) BETWEEN 1 AND 32
        AND octet_length(selections::text) <= 8192
    ),
    plan_digest bytea NOT NULL CHECK (octet_length(plan_digest) = 32),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_job_evidence_tasks(tenant_id, job_id)
);
ALTER TABLE omnixat.agent_job_csv_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_csv_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_csv_plans
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_csv_plans FROM PUBLIC;
