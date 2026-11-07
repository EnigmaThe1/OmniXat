-- The primary and scoped foreign-key indexes enforce the same logical keys.
-- Handle collisions on either index before comparing the stored receipt.
CREATE OR REPLACE FUNCTION omnixat_extraction.record_expense_journal_decision(
    organisation uuid, requested_journal uuid, expected_snapshot bytea, requested_decision text, actor_id text
)
RETURNS TABLE (outcome text, decision_recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    current_snapshot bytea;
    stored_decision text;
    stored_at timestamptz;
BEGIN
    SELECT j.snapshot_sha256 INTO current_snapshot
    FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j;
    IF current_snapshot IS NULL OR current_snapshot IS DISTINCT FROM expected_snapshot THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_review_decisions
        (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, decision)
    VALUES (tenant, organisation, requested_journal, current_snapshot, actor_id, requested_decision)
    ON CONFLICT DO NOTHING;

    SELECT d.decision, d.recorded_at INTO STRICT stored_decision, stored_at
    FROM omnixat.expense_journal_review_decisions d
    WHERE d.tenant_id = tenant AND d.organisation_id = organisation AND d.journal_id = requested_journal
      AND d.snapshot_sha256 = current_snapshot AND d.reviewer_id = actor_id;
    IF stored_decision IS DISTINCT FROM requested_decision THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, stored_at;
END;
$$;

CREATE OR REPLACE FUNCTION omnixat_extraction.record_expense_journal_correction(
    organisation uuid, requested_journal uuid, expected_snapshot bytea, requested_reason text, actor_id text
)
RETURNS TABLE (outcome text, correction_recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    stored_reason text;
    stored_at timestamptz;
BEGIN
    PERFORM 1 FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
    JOIN omnixat.expense_journal_review_decisions d
      ON d.tenant_id = tenant AND d.organisation_id = organisation
     AND d.journal_id = j.journal_id AND d.snapshot_sha256 = j.snapshot_sha256
     AND d.reviewer_id = actor_id AND d.decision = 'changes_requested'
    WHERE j.snapshot_sha256 = expected_snapshot
    FOR KEY SHARE OF d;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_correction_requests
        (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, reason)
    VALUES (tenant, organisation, requested_journal, expected_snapshot, actor_id, requested_reason)
    ON CONFLICT DO NOTHING;

    SELECT c.reason, c.recorded_at INTO STRICT stored_reason, stored_at
    FROM omnixat.expense_journal_correction_requests c
    WHERE c.tenant_id = tenant AND c.organisation_id = organisation AND c.journal_id = requested_journal
      AND c.snapshot_sha256 = expected_snapshot AND c.reviewer_id = actor_id;
    IF stored_reason IS DISTINCT FROM requested_reason THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, stored_at;
END;
$$;

CREATE OR REPLACE FUNCTION omnixat_extraction.record_expense_journal_clarification(
    organisation uuid, requested_journal uuid, expected_snapshot bytea,
    requested_reviewer text, requested_reason text, supplied_answer text, actor_id text
)
RETURNS TABLE (outcome text, correction_reviewer text, recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    stored omnixat.expense_journal_clarification_answers%ROWTYPE;
BEGIN
    -- Hold the scan policy through the answer transaction, as for CSV clarifications.
    PERFORM 1 FROM omnixat_extraction.active_scan_policy FOR SHARE;
    INSERT INTO omnixat.expense_journal_clarification_answers AS a
        (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, reason, answer, answered_by)
    SELECT c.tenant_id, c.organisation_id, c.journal_id, c.snapshot_sha256, c.reviewer_id, c.reason,
           supplied_answer, actor_id
    FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
    JOIN omnixat.expense_journal_correction_requests c
      ON c.tenant_id = tenant AND c.organisation_id = organisation
     AND c.journal_id = j.journal_id AND c.snapshot_sha256 = j.snapshot_sha256
    WHERE j.snapshot_sha256 = expected_snapshot AND c.reviewer_id = requested_reviewer
      AND c.reason = requested_reason
    ON CONFLICT DO NOTHING
    RETURNING a.* INTO stored;

    IF NOT FOUND THEN
        -- A competing insert may have committed after the INSERT's snapshot.
        SELECT a.* INTO stored
        FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
        JOIN omnixat.expense_journal_clarification_answers a
          ON a.tenant_id = tenant AND a.organisation_id = organisation
         AND a.journal_id = j.journal_id AND a.snapshot_sha256 = j.snapshot_sha256
        JOIN omnixat.expense_journal_correction_requests c
          ON (c.tenant_id, c.organisation_id, c.journal_id, c.snapshot_sha256, c.reason)
           = (a.tenant_id, a.organisation_id, a.journal_id, a.snapshot_sha256, a.reason)
        WHERE j.snapshot_sha256 = expected_snapshot AND c.reviewer_id = requested_reviewer
          AND a.reason = requested_reason;
        IF NOT FOUND THEN
            RETURN QUERY SELECT 'unavailable'::text, NULL::text, NULL::timestamptz;
            RETURN;
        END IF;
        IF (stored.answer, stored.answered_by) IS DISTINCT FROM (supplied_answer, actor_id) THEN
            RETURN QUERY SELECT 'conflict'::text, NULL::text, NULL::timestamptz;
            RETURN;
        END IF;
    END IF;

    RETURN QUERY SELECT 'stored'::text, stored.reviewer_id, stored.answered_at;
END;
$$;
