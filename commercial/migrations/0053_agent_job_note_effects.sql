CREATE TABLE omnixat.agent_job_note_effects (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    key_digest bytea NOT NULL CHECK (octet_length(key_digest) = 32),
    payload_digest bytea NOT NULL CHECK (octet_length(payload_digest) = 32),
    note_id uuid NOT NULL,
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, job_id, key_digest),
    UNIQUE (tenant_id, note_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_jobs(tenant_id, id),
    FOREIGN KEY (tenant_id, note_id) REFERENCES omnixat.notes(tenant_id, id)
);
ALTER TABLE omnixat.agent_job_note_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_note_effects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_note_effects
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_note_effects FROM PUBLIC;
