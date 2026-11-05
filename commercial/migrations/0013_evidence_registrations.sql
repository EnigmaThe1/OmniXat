CREATE TABLE omnixat.evidence_registrations (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
    media_type text NOT NULL CHECK (media_type IN ('application/pdf', 'image/jpeg', 'image/png', 'text/csv')),
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 20971520),
    registered_by text NOT NULL CHECK (length(btrim(registered_by)) BETWEEN 1 AND 200),
    registered_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, organisation_id, content_sha256),
    FOREIGN KEY (tenant_id, organisation_id) REFERENCES omnixat.organisations(tenant_id, id)
);

ALTER TABLE omnixat.evidence_registrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_registrations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_registrations
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.evidence_registrations FROM PUBLIC;
