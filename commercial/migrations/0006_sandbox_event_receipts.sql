CREATE TABLE omnixat_sandbox.event_receipts (
    tenant_id uuid NOT NULL,
    event_id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    body_digest bytea NOT NULL CHECK (octet_length(body_digest) = 32),
    reported_price_version_id uuid NOT NULL,
    reported_state text NOT NULL CHECK (reported_state IN ('pending','trialing','trial_expired','cancelled','active')),
    observed_state text NOT NULL CHECK (observed_state IN ('pending','trialing','trial_expired','cancelled')),
    outcome text NOT NULL CHECK (outcome IN ('matched','price_mismatch','state_mismatch')),
    received_at timestamptz NOT NULL CHECK (isfinite(received_at)),
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id, subscription_id)
        REFERENCES omnixat_sandbox.subscriptions(tenant_id, id)
);
CREATE INDEX sandbox_event_receipts_subscription
    ON omnixat_sandbox.event_receipts (tenant_id, subscription_id);
ALTER TABLE omnixat_sandbox.event_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat_sandbox.event_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY sandbox_event_tenant ON omnixat_sandbox.event_receipts
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat_sandbox.event_receipts FROM PUBLIC;
