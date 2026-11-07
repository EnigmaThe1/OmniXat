CREATE FUNCTION omnixat_extraction.read_saved_expense_journal_replacement(
    organisation uuid, requested_replacement uuid
)
RETURNS TABLE (
    replacement_id uuid, replacement_created_by text, replacement_created_at timestamptz,
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
    SELECT r.id, r.created_by, r.created_at, p.*
    FROM omnixat.expense_journal_replacements r
    CROSS JOIN LATERAL omnixat_extraction.read_expense_journal_replacement_preview(
        r.organisation_id, r.proposal_id, r.proposal_sha256, r.reviewer_id
    ) p
    WHERE r.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND r.organisation_id = organisation AND r.id = requested_replacement
      AND r.currency = 'GBP' AND r.review_decision = 'reviewed'
      AND (r.original_journal_id, r.original_snapshot_sha256, r.reviewed_at,
           r.accounting_date, r.period_id, r.funding_source_id, r.expense_account_id,
           r.counterpart_account_id, r.amount_pence, r.evidence_id, r.job_id,
           r.field_name, r.source_row, r.source_column, r.content_sha256, r.scan_policy_version)
        = (p.journal_id, p.snapshot_sha256, p.reviewed_at,
           p.accounting_date, p.period_id, p.funding_source_id, p.expense_account_id,
           p.counterpart_account_id, p.amount::numeric * 100, p.evidence_id, p.job_id,
           p.field_name, p.source_row, p.source_column, p.content_sha256, p.policy_version);
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_saved_expense_journal_replacement(uuid,uuid) FROM PUBLIC;
