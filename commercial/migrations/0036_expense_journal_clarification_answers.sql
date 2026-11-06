ALTER TABLE omnixat.expense_journal_correction_requests
    ADD UNIQUE (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, reason);

CREATE TABLE omnixat.expense_journal_clarification_answers (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    journal_id uuid NOT NULL,
    snapshot_sha256 bytea NOT NULL,
    reviewer_id text NOT NULL,
    reason text NOT NULL,
    answer text NOT NULL CHECK (
        char_length(answer) BETWEEN 1 AND 1000 AND btrim(answer) <> '' AND answer !~ '[[:cntrl:]]'
    ),
    answered_by text NOT NULL CHECK (char_length(answered_by) BETWEEN 1 AND 200 AND btrim(answered_by) <> ''),
    answered_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, journal_id, snapshot_sha256, reason),
    FOREIGN KEY (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, reason)
        REFERENCES omnixat.expense_journal_correction_requests
            (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, reason)
);

ALTER TABLE omnixat.expense_journal_clarification_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_clarification_answers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_clarification_answers
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_clarification_answers FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.record_expense_journal_clarification(
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
    ON CONFLICT (tenant_id, journal_id, snapshot_sha256, reason) DO NOTHING
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

REVOKE ALL ON FUNCTION omnixat_extraction.record_expense_journal_clarification(uuid,uuid,bytea,text,text,text,text)
    FROM PUBLIC;
