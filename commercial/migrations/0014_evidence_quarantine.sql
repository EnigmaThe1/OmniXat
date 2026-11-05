-- Bind the stored original to the fingerprint and length of its registration.
ALTER TABLE omnixat.evidence_registrations
    ADD UNIQUE (tenant_id, id, content_sha256, byte_size);

CREATE TABLE omnixat.evidence_quarantine (
    tenant_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    original_bytes bytea NOT NULL,
    content_sha256 bytea GENERATED ALWAYS AS (pg_catalog.sha256(original_bytes)) STORED,
    byte_size integer GENERATED ALWAYS AS (pg_catalog.octet_length(original_bytes)) STORED,
    stored_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, evidence_id),
    CHECK (byte_size BETWEEN 1 AND 20971520),
    FOREIGN KEY (tenant_id, evidence_id, content_sha256, byte_size)
        REFERENCES omnixat.evidence_registrations(tenant_id, id, content_sha256, byte_size)
);

ALTER TABLE omnixat.evidence_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_quarantine FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_quarantine
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.evidence_quarantine FROM PUBLIC;
