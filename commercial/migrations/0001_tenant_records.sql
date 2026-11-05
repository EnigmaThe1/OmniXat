-- Run only with a separate migration owner, never the runtime identity.
CREATE SCHEMA omnixat;
REVOKE ALL ON SCHEMA omnixat FROM PUBLIC;
CREATE TABLE omnixat.tenants (
    id uuid PRIMARY KEY,
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200)
);
CREATE TABLE omnixat.organisations (
    tenant_id uuid NOT NULL REFERENCES omnixat.tenants(id),
    id uuid NOT NULL,
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    created_by text NOT NULL CHECK (length(created_by) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE omnixat.notes (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    body text NOT NULL CHECK (length(btrim(body)) BETWEEN 1 AND 10000),
    created_by text NOT NULL CHECK (length(created_by) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, organisation_id)
        REFERENCES omnixat.organisations(tenant_id, id)
);
CREATE INDEX notes_organisation ON omnixat.notes (tenant_id, organisation_id, id);
ALTER TABLE omnixat.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE omnixat.organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.organisations FORCE ROW LEVEL SECURITY;
ALTER TABLE omnixat.notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.notes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.tenants
    USING (id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
CREATE POLICY tenant_scope ON omnixat.organisations
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
CREATE POLICY tenant_scope ON omnixat.notes
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON ALL TABLES IN SCHEMA omnixat FROM PUBLIC;
-- Deployment provisions a non-owner NOSUPERUSER NOBYPASSRLS runtime login.
-- Grant schema USAGE; tenants SELECT; organisations/notes SELECT, INSERT only.
-- Tenant provisioning and membership administration are separate trusted services.
