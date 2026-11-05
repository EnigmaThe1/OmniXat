CREATE SCHEMA omnixat_metrics;
REVOKE ALL ON SCHEMA omnixat_metrics FROM PUBLIC;

-- A fixed projection uses the migration owner's SELECT policies, even when
-- FORCE RLS applies to that owner. Never grant runtime membership in that role.
CREATE POLICY sandbox_metrics_subscriptions ON omnixat_sandbox.subscriptions
    FOR SELECT TO CURRENT_USER USING (true);
CREATE POLICY sandbox_metrics_cancellations ON omnixat_sandbox.cancellations
    FOR SELECT TO CURRENT_USER USING (true);
CREATE POLICY sandbox_metrics_events ON omnixat_sandbox.event_receipts
    FOR SELECT TO CURRENT_USER USING (true);

CREATE VIEW omnixat_metrics.sandbox_snapshot WITH (security_barrier = true) AS
WITH states AS (
    SELECT CASE
        WHEN c.cancelled_at <= statement_timestamp() THEN 'cancelled'
        WHEN s.trial_ends_at IS NULL THEN 'pending'
        WHEN s.trial_ends_at <= statement_timestamp() THEN 'trial_expired'
        ELSE 'trialing'
    END AS state
    FROM omnixat_sandbox.subscriptions s
    LEFT JOIN omnixat_sandbox.cancellations c
        ON c.tenant_id = s.tenant_id AND c.subscription_id = s.id
    WHERE s.started_at <= statement_timestamp()
), subscriptions AS (
    SELECT count(*) FILTER (WHERE state = 'pending') AS pending,
           count(*) FILTER (WHERE state = 'trialing') AS trialing,
           count(*) FILTER (WHERE state = 'trial_expired') AS trial_expired,
           count(*) FILTER (WHERE state = 'cancelled') AS cancelled
    FROM states
), receipts AS (
    SELECT count(*) FILTER (WHERE outcome = 'matched') AS matched,
           count(*) FILTER (WHERE outcome = 'price_mismatch') AS price_mismatch,
           count(*) FILTER (WHERE outcome = 'state_mismatch') AS state_mismatch
    FROM omnixat_sandbox.event_receipts
    WHERE received_at <= statement_timestamp()
)
SELECT statement_timestamp() AS observed_at,
       pending, trialing, trial_expired, cancelled,
       matched, price_mismatch, state_mismatch
FROM subscriptions CROSS JOIN receipts;

REVOKE ALL ON omnixat_metrics.sandbox_snapshot FROM PUBLIC;
