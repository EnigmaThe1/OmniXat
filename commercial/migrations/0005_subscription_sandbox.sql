CREATE SCHEMA omnixat_sandbox;
REVOKE ALL ON SCHEMA omnixat_sandbox FROM PUBLIC;

-- Narrow read-only grant target. The runtime does not need access to the
-- billing schema or to catalogue staff attribution.
CREATE VIEW omnixat_sandbox.price_terms AS
    SELECT id, plan, amount_minor, currency, interval, trial_days, api_allowance, effective_at
    FROM omnixat_billing.price_versions;

CREATE TABLE omnixat_sandbox.subscriptions (
    tenant_id uuid PRIMARY KEY REFERENCES omnixat.tenants(id),
    id uuid NOT NULL,
    price_version_id uuid NOT NULL REFERENCES omnixat_billing.price_versions(id),
    started_at timestamptz NOT NULL CHECK (isfinite(started_at)),
    trial_ends_at timestamptz CHECK (isfinite(trial_ends_at) AND trial_ends_at > started_at),
    started_by text NOT NULL CHECK (length(started_by) BETWEEN 1 AND 200),
    UNIQUE (tenant_id, id)
);
CREATE INDEX sandbox_subscriptions_price ON omnixat_sandbox.subscriptions (price_version_id);

CREATE TABLE omnixat_sandbox.cancellations (
    tenant_id uuid PRIMARY KEY,
    subscription_id uuid NOT NULL,
    cancelled_at timestamptz NOT NULL CHECK (isfinite(cancelled_at)),
    cancelled_by text NOT NULL CHECK (length(cancelled_by) BETWEEN 1 AND 200),
    FOREIGN KEY (tenant_id, subscription_id)
        REFERENCES omnixat_sandbox.subscriptions(tenant_id, id)
);

ALTER TABLE omnixat_sandbox.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat_sandbox.subscriptions FORCE ROW LEVEL SECURITY;
ALTER TABLE omnixat_sandbox.cancellations ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat_sandbox.cancellations FORCE ROW LEVEL SECURITY;
CREATE POLICY sandbox_subscription_tenant ON omnixat_sandbox.subscriptions
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
CREATE POLICY sandbox_cancellation_tenant ON omnixat_sandbox.cancellations
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON ALL TABLES IN SCHEMA omnixat_sandbox FROM PUBLIC;
-- Provision a separate sandbox login with schema USAGE, view SELECT and
-- table SELECT/INSERT only; do not grant it customer or staff catalogue access.
