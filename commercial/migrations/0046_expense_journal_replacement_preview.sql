CREATE FUNCTION omnixat_extraction.read_expense_journal_replacement_preview(
    organisation uuid, requested_proposal uuid, expected_proposal bytea, requested_reviewer text
)
RETURNS TABLE (
    proposal_id uuid, journal_id uuid, snapshot_sha256 bytea, created_by text, created_at timestamptz,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    content_sha256 bytea, policy_version text, amount text, previous_pence numeric,
    expense_account_id uuid, counterpart_account_id uuid, proposal_sha256 bytea,
    reviewer_id text, reviewed_at timestamptz, accounting_date date, period_id uuid, funding_source_id uuid
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT p.*, d.reviewer_id, d.recorded_at, j.accounting_date, j.period_id, j.funding_source_id
    FROM omnixat_extraction.read_expense_journal_amount_correction_review(organisation, requested_proposal) p
    JOIN omnixat.expense_journal_amount_correction_decisions d
      ON d.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND d.organisation_id = organisation AND d.proposal_id = p.proposal_id
     AND d.proposal_sha256 = p.proposal_sha256 AND d.reviewer_id = requested_reviewer
     AND d.decision = 'reviewed'
    CROSS JOIN LATERAL omnixat_extraction.read_expense_journal_review(organisation, p.journal_id) j
    WHERE p.proposal_sha256 = expected_proposal AND j.snapshot_sha256 = p.snapshot_sha256;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_replacement_preview(uuid,uuid,bytea,text)
    FROM PUBLIC;
