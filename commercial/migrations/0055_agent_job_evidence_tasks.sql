CREATE TABLE omnixat.agent_job_evidence_tasks (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version = 1),
    kind text NOT NULL DEFAULT 'prepare_evidence' CHECK (kind = 'prepare_evidence'),
    organisation_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_jobs(tenant_id, id),
    FOREIGN KEY (tenant_id, organisation_id, evidence_id, content_sha256)
        REFERENCES omnixat.evidence_registrations(tenant_id, organisation_id, id, content_sha256)
);
ALTER TABLE omnixat.agent_job_evidence_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_evidence_tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_evidence_tasks
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_evidence_tasks FROM PUBLIC;
