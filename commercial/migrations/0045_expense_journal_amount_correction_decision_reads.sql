CREATE FUNCTION omnixat_extraction.read_expense_journal_amount_correction_decisions(
    organisation uuid, requested_proposal uuid, expected_proposal bytea,
    after_reviewer text, page_size integer
)
RETURNS TABLE (reviewer_id text, decision text, recorded_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT page.reviewer_id, page.decision, page.recorded_at
    FROM omnixat_extraction.read_expense_journal_amount_correction_review(organisation, requested_proposal) p
    LEFT JOIN LATERAL (
        SELECT d.reviewer_id, d.decision, d.recorded_at
        FROM omnixat.expense_journal_amount_correction_decisions d
        WHERE d.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
          AND d.organisation_id = organisation AND d.proposal_id = p.proposal_id
          AND d.proposal_sha256 = p.proposal_sha256
          AND (after_reviewer IS NULL OR d.reviewer_id > after_reviewer)
        ORDER BY d.reviewer_id
        LIMIT CASE WHEN page_size BETWEEN 1 AND 100 THEN page_size + 1 ELSE 0 END
    ) page ON true
    WHERE p.proposal_sha256 = expected_proposal AND page_size BETWEEN 1 AND 100
    ORDER BY page.reviewer_id;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_amount_correction_decisions(uuid,uuid,bytea,text,integer)
    FROM PUBLIC;
