ALTER TABLE omnixat.expense_journal_clarification_answers
    ADD UNIQUE (tenant_id, organisation_id, journal_id, snapshot_sha256, reason);

ALTER TABLE omnixat.evidence_registrations
    ADD UNIQUE (tenant_id, organisation_id, id, content_sha256);

CREATE TABLE omnixat.expense_journal_clarification_evidence (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    journal_id uuid NOT NULL,
    snapshot_sha256 bytea NOT NULL,
    reason text NOT NULL,
    evidence_id uuid NOT NULL,
    content_sha256 bytea NOT NULL,
    policy_version text NOT NULL,
    linked_by text NOT NULL CHECK (char_length(linked_by) BETWEEN 1 AND 200 AND btrim(linked_by) <> ''),
    linked_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, journal_id, snapshot_sha256, reason),
    FOREIGN KEY (tenant_id, organisation_id, journal_id, snapshot_sha256, reason)
        REFERENCES omnixat.expense_journal_clarification_answers
            (tenant_id, organisation_id, journal_id, snapshot_sha256, reason),
    FOREIGN KEY (tenant_id, organisation_id, evidence_id, content_sha256)
        REFERENCES omnixat.evidence_registrations (tenant_id, organisation_id, id, content_sha256)
);

ALTER TABLE omnixat.expense_journal_clarification_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_clarification_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_clarification_evidence
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_clarification_evidence FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.link_expense_journal_clarification_evidence(
    organisation uuid, requested_journal uuid, expected_snapshot bytea,
    requested_reason text, requested_evidence uuid, actor_id text
)
RETURNS TABLE (outcome text, fingerprint bytea, scan_policy text, recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    active_policy text;
    eligible_fingerprint bytea;
    stored omnixat.expense_journal_clarification_evidence%ROWTYPE;
BEGIN
    SELECT p.policy_version INTO active_policy
    FROM omnixat_extraction.active_scan_policy p FOR SHARE;

    -- Use the journal writer's quarantine/claim lock order. A new claim
    -- needs a foreign-key lock on quarantine and an existing claim can be reclaimed.
    PERFORM 1
    FROM omnixat.evidence_quarantine q
    JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
    WHERE q.tenant_id = tenant AND q.evidence_id = requested_evidence AND r.organisation_id = organisation
    FOR UPDATE OF q FOR SHARE OF r;

    IF FOUND AND active_policy IS NOT NULL THEN
        PERFORM 1 FROM omnixat.evidence_scan_claims c
        WHERE c.tenant_id = tenant AND c.evidence_id = requested_evidence AND c.policy_version = active_policy
        FOR SHARE NOWAIT;
        SELECT e.content_sha256 INTO eligible_fingerprint
        FROM omnixat_extraction.read_eligible_original(organisation, requested_evidence) e;
    END IF;

    IF eligible_fingerprint IS NULL OR NOT EXISTS (
        SELECT 1 FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
        JOIN omnixat.expense_journal_clarification_answers a
          ON a.tenant_id = tenant AND a.organisation_id = organisation
         AND a.journal_id = j.journal_id AND a.snapshot_sha256 = j.snapshot_sha256
        WHERE j.snapshot_sha256 = expected_snapshot AND a.reason = requested_reason
    ) THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::bytea, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_clarification_evidence
        (tenant_id, organisation_id, journal_id, snapshot_sha256, reason,
         evidence_id, content_sha256, policy_version, linked_by)
    VALUES (tenant, organisation, requested_journal, expected_snapshot, requested_reason,
            requested_evidence, eligible_fingerprint, active_policy, actor_id)
    ON CONFLICT (tenant_id, journal_id, snapshot_sha256, reason) DO NOTHING;

    SELECT l.* INTO STRICT stored FROM omnixat.expense_journal_clarification_evidence l
    WHERE l.tenant_id = tenant AND l.organisation_id = organisation AND l.journal_id = requested_journal
      AND l.snapshot_sha256 = expected_snapshot AND l.reason = requested_reason;
    IF (stored.evidence_id, stored.content_sha256, stored.policy_version, stored.linked_by)
       IS DISTINCT FROM (requested_evidence, eligible_fingerprint, active_policy, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::bytea, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, stored.content_sha256, stored.policy_version, stored.linked_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.link_expense_journal_clarification_evidence(uuid,uuid,bytea,text,uuid,text)
    FROM PUBLIC;
