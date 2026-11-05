CREATE SCHEMA omnixat_staff_maintenance;
REVOKE ALL ON SCHEMA omnixat_staff_maintenance FROM PUBLIC;

-- Operators receive aggregate counts and cannot choose a cutoff or access the
-- underlying tables. Cap direct SQL calls as well as any future job wrapper.
CREATE FUNCTION omnixat_staff_maintenance.prune_expired(batch_size integer DEFAULT 100)
RETURNS TABLE (login_attempts_deleted bigint, staff_sessions_deleted bigint)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET lock_timeout = '1s'
AS $$
    WITH expired_attempts AS (
        SELECT state_key
        FROM omnixat_staff_login.transactions
        WHERE expires_at <= statement_timestamp()
        ORDER BY expires_at
        LIMIT LEAST(GREATEST(COALESCE(batch_size, 0), 0), 500)
        FOR UPDATE SKIP LOCKED
    ), deleted_attempts AS (
        DELETE FROM omnixat_staff_login.transactions AS t
        USING expired_attempts AS e
        WHERE t.state_key = e.state_key
        RETURNING 1
    ), expired_sessions AS (
        SELECT token_digest
        FROM omnixat_staff_session.sessions
        WHERE expires_at <= statement_timestamp()
        ORDER BY expires_at
        LIMIT LEAST(GREATEST(COALESCE(batch_size, 0), 0), 500)
        FOR UPDATE SKIP LOCKED
    ), deleted_sessions AS (
        DELETE FROM omnixat_staff_session.sessions AS s
        USING expired_sessions AS e
        WHERE s.token_digest = e.token_digest
        RETURNING 1
    )
    SELECT (SELECT count(*) FROM deleted_attempts), (SELECT count(*) FROM deleted_sessions);
$$;

REVOKE ALL ON FUNCTION omnixat_staff_maintenance.prune_expired(integer) FROM PUBLIC;
