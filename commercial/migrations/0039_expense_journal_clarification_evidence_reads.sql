CREATE FUNCTION omnixat_extraction.read_expense_journal_decisions_with_evidence(
    organisation uuid, requested_journal uuid, expected_snapshot bytea,
    after_reviewer text, page_size integer
)
RETURNS TABLE (
    reviewer_id text, decision text, recorded_at timestamptz,
    correction_reason text, correction_recorded_at timestamptz,
    answer text, answered_by text, answered_at timestamptz, answer_reviewer_id text,
    evidence_id uuid, evidence_fingerprint bytea, evidence_scan_policy text,
    evidence_linked_by text, evidence_linked_at timestamptz, evidence_is_eligible boolean
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT d.*, l.evidence_id, l.content_sha256, l.policy_version, l.linked_by, l.linked_at,
           CASE WHEN l.evidence_id IS NOT NULL THEN EXISTS (
               SELECT 1 FROM omnixat_extraction.read_eligible_original(organisation, l.evidence_id) e
               WHERE e.content_sha256 = l.content_sha256
           ) END
    FROM omnixat_extraction.read_expense_journal_decisions_with_answers(
        organisation, requested_journal, expected_snapshot, after_reviewer, page_size
    ) d
    LEFT JOIN omnixat.expense_journal_clarification_evidence l
      ON l.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND l.organisation_id = organisation AND l.journal_id = requested_journal
     AND l.snapshot_sha256 = expected_snapshot AND l.reason = d.correction_reason
     -- The answer reader withholds answers from its pagination lookahead row.
     AND d.answered_at IS NOT NULL
    ORDER BY d.reviewer_id;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_decisions_with_evidence(uuid,uuid,bytea,text,integer)
    FROM PUBLIC;
