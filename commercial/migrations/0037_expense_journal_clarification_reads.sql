CREATE FUNCTION omnixat_extraction.read_expense_journal_decisions_with_answers(
    organisation uuid, requested_journal uuid, expected_snapshot bytea,
    after_reviewer text, page_size integer
)
RETURNS TABLE (
    reviewer_id text, decision text, recorded_at timestamptz,
    correction_reason text, correction_recorded_at timestamptz,
    answer text, answered_by text, answered_at timestamptz, answer_reviewer_id text
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT d.reviewer_id, d.decision, d.recorded_at, d.correction_reason, d.correction_recorded_at,
           a.answer, a.answered_by, a.answered_at, a.reviewer_id
    FROM (
        SELECT page.*, row_number() OVER (ORDER BY page.reviewer_id) AS page_position
        FROM omnixat_extraction.read_expense_journal_decisions_with_corrections(
            organisation, requested_journal, expected_snapshot, after_reviewer, page_size
        ) page
    ) d
    LEFT JOIN omnixat.expense_journal_clarification_answers a
      ON a.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND a.organisation_id = organisation AND a.journal_id = requested_journal
     AND a.snapshot_sha256 = expected_snapshot AND a.reason = d.correction_reason
     AND d.page_position <= page_size
    ORDER BY d.reviewer_id;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_decisions_with_answers(uuid,uuid,bytea,text,integer)
    FROM PUBLIC;
