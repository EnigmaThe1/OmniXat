ALTER TABLE omnixat.expense_journal_review_decisions
    ADD UNIQUE (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, decision);

CREATE TABLE omnixat.expense_journal_correction_requests (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    journal_id uuid NOT NULL,
    snapshot_sha256 bytea NOT NULL,
    reviewer_id text NOT NULL,
    parent_decision text NOT NULL DEFAULT 'changes_requested' CHECK (parent_decision = 'changes_requested'),
    reason text NOT NULL CHECK (reason IN ('amount', 'account', 'funding', 'accounting_date', 'source_evidence')),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, journal_id, snapshot_sha256, reviewer_id),
    FOREIGN KEY (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, parent_decision)
        REFERENCES omnixat.expense_journal_review_decisions
            (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, decision)
);

ALTER TABLE omnixat.expense_journal_correction_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_correction_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_correction_requests
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_correction_requests FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.record_expense_journal_correction(
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
    ON CONFLICT (tenant_id, journal_id, snapshot_sha256, reviewer_id) DO NOTHING;

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

REVOKE ALL ON FUNCTION omnixat_extraction.record_expense_journal_correction(uuid,uuid,bytea,text,text) FROM PUBLIC;
