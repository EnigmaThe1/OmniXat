-- Platform-global catalogue. Keep the staff runtime separate from tenant data.
CREATE SCHEMA omnixat_billing;
REVOKE ALL ON SCHEMA omnixat_billing FROM PUBLIC;

CREATE TABLE omnixat_billing.plans (
    code text PRIMARY KEY CHECK (code ~ '^[a-z][a-z0-9-]{0,63}$'),
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 80),
    created_by text NOT NULL CHECK (length(created_by) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE omnixat_billing.price_versions (
    id uuid PRIMARY KEY,
    plan text NOT NULL REFERENCES omnixat_billing.plans(code),
    amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
    currency text NOT NULL CHECK (currency = 'GBP'),
    interval text NOT NULL CHECK (interval IN ('month', 'year')),
    trial_days integer NOT NULL CHECK (trial_days >= 0),
    api_allowance bigint NOT NULL CHECK (api_allowance >= 0),
    effective_at timestamptz NOT NULL CHECK (isfinite(effective_at)),
    created_by text NOT NULL CHECK (length(created_by) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (plan, interval, effective_at)
);

CREATE INDEX price_versions_audit_order
    ON omnixat_billing.price_versions (plan, created_at DESC, id DESC);
REVOKE ALL ON ALL TABLES IN SCHEMA omnixat_billing FROM PUBLIC;
-- Separate non-owner pricing runtime: USAGE on omnixat_billing and SELECT,
-- INSERT on these two tables only. Do not grant access to omnixat tenant data.
