ALTER TABLE omnixat.evidence_quarantine
    ADD UNIQUE (tenant_id, evidence_id, content_sha256, byte_size);

CREATE TABLE omnixat.evidence_scan_verdicts (
    tenant_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    content_sha256 bytea NOT NULL,
    byte_size integer NOT NULL,
    policy_version text NOT NULL CHECK (
        policy_version COLLATE "C" ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$'
    ),
    verdict text NOT NULL CHECK (verdict IN ('clean', 'blocked')),
    recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, evidence_id, policy_version, verdict),
    FOREIGN KEY (tenant_id, evidence_id, content_sha256, byte_size)
        REFERENCES omnixat.evidence_quarantine(tenant_id, evidence_id, content_sha256, byte_size)
);

ALTER TABLE omnixat.evidence_scan_verdicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_scan_verdicts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_scan_verdicts
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.evidence_scan_verdicts FROM PUBLIC;
