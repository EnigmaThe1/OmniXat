CREATE FUNCTION omnixat_extraction.read_current_expense_journal(organisation uuid, requested_journal uuid)
RETURNS TABLE (
    journal_id uuid, expense_draft_id uuid, journal_created_at timestamptz, journal_created_by text,
    expense_account_id uuid, counterpart_account_id uuid, funding_source_id uuid,
    amount_pence numeric, currency text, accounting_date date, period_id uuid,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    policy_version text, content_sha256 bytea, snapshot_sha256 bytea,
    r_replacement_id uuid, r_replacement_created_by text, r_replacement_created_at timestamptz,
    r_proposal_id uuid, r_journal_id uuid, r_snapshot_sha256 bytea, r_created_by text, r_created_at timestamptz,
    r_evidence_id uuid, r_job_id uuid, r_field_name text, r_source_row integer, r_source_column integer,
    r_content_sha256 bytea, r_policy_version text, r_amount text, r_previous_pence numeric,
    r_expense_account_id uuid, r_counterpart_account_id uuid, r_proposal_sha256 bytea,
    r_reviewer_id text, r_reviewed_at timestamptz, r_accounting_date date, r_period_id uuid, r_funding_source_id uuid,
    selected_by text, selected_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT j.*, r.*, s.selected_by, s.selected_at
    FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
    LEFT JOIN omnixat.expense_journal_replacement_selections s
      ON s.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND s.original_journal_id = j.journal_id
    LEFT JOIN LATERAL omnixat_extraction.read_saved_expense_journal_replacement(
        organisation, s.replacement_id
    ) r ON true
    WHERE s.original_journal_id IS NULL
       OR (s.organisation_id = organisation AND r.journal_id = j.journal_id
           AND r.replacement_id = s.replacement_id
           AND s.original_snapshot_sha256 = j.snapshot_sha256
           AND s.original_snapshot_sha256 = r.snapshot_sha256
           AND s.proposal_sha256 = r.proposal_sha256);
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_current_expense_journal(uuid,uuid) FROM PUBLIC;
