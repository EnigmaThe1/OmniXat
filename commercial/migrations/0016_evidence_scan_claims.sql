CREATE TABLE omnixat.evidence_scan_claims (
    tenant_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    policy_version text NOT NULL CHECK (
        policy_version COLLATE "C" ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$'
    ),
    lease_token uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, evidence_id, policy_version),
    FOREIGN KEY (tenant_id, evidence_id)
        REFERENCES omnixat.evidence_quarantine(tenant_id, evidence_id)
);

ALTER TABLE omnixat.evidence_scan_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_scan_claims FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_scan_claims
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.evidence_scan_claims FROM PUBLIC;
