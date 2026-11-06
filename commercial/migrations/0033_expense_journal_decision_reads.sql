CREATE FUNCTION omnixat_extraction.read_expense_journal_decisions(
    organisation uuid, requested_journal uuid, expected_snapshot bytea,
    after_reviewer text, page_size integer
)
RETURNS TABLE (reviewer_id text, decision text, recorded_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT page.reviewer_id, page.decision, page.recorded_at
    FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
    LEFT JOIN LATERAL (
        SELECT d.reviewer_id, d.decision, d.recorded_at
        FROM omnixat.expense_journal_review_decisions d
        WHERE d.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
          AND d.organisation_id = organisation AND d.journal_id = j.journal_id
          AND d.snapshot_sha256 = j.snapshot_sha256
          AND (after_reviewer IS NULL OR d.reviewer_id > after_reviewer)
        ORDER BY d.reviewer_id
        LIMIT CASE WHEN page_size BETWEEN 1 AND 100 THEN page_size + 1 ELSE 0 END
    ) page ON true
    WHERE j.snapshot_sha256 = expected_snapshot AND page_size BETWEEN 1 AND 100
    ORDER BY page.reviewer_id;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_decisions(uuid,uuid,bytea,text,integer) FROM PUBLIC;
