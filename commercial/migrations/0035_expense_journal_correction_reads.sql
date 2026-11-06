CREATE FUNCTION omnixat_extraction.read_expense_journal_decisions_with_corrections(
    organisation uuid, requested_journal uuid, expected_snapshot bytea,
    after_reviewer text, page_size integer
)
RETURNS TABLE (
    reviewer_id text, decision text, recorded_at timestamptz,
    correction_reason text, correction_recorded_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT d.reviewer_id, d.decision, d.recorded_at, c.reason, c.recorded_at
    FROM omnixat_extraction.read_expense_journal_decisions(
        organisation, requested_journal, expected_snapshot, after_reviewer, page_size
    ) d
    LEFT JOIN omnixat.expense_journal_correction_requests c
      ON c.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND c.organisation_id = organisation AND c.journal_id = requested_journal
     AND c.snapshot_sha256 = expected_snapshot AND c.reviewer_id = d.reviewer_id
     AND c.parent_decision = d.decision
    ORDER BY d.reviewer_id;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_decisions_with_corrections(uuid,uuid,bytea,text,integer)
    FROM PUBLIC;
