CREATE FUNCTION omnixat_extraction.read_saved_expense_journal_amount_correction(
    organisation uuid, requested_proposal uuid
)
RETURNS TABLE (
    proposal_id uuid, journal_id uuid, snapshot_sha256 bytea, created_by text, created_at timestamptz,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    content_sha256 bytea, policy_version text, amount text, previous_pence numeric,
    expense_account_id uuid, counterpart_account_id uuid
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT p.id, p.journal_id, p.snapshot_sha256, p.created_by, p.created_at,
           c.evidence_id, p.job_id, p.field_name, p.source_row, p.source_column,
           c.content_sha256, c.policy_version, c.amount, c.previous_pence,
           c.expense_account_id, c.counterpart_account_id
    FROM omnixat.expense_journal_amount_corrections p
    CROSS JOIN LATERAL omnixat_extraction.read_expense_journal_amount_correction(
        p.organisation_id, p.journal_id, p.snapshot_sha256, p.job_id,
        p.field_name, p.source_row, p.source_column
    ) c
    WHERE p.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND p.organisation_id = organisation AND p.id = requested_proposal AND p.currency = 'GBP'
      AND (p.evidence_id, p.content_sha256, p.scan_policy_version, p.previous_pence,
           p.proposed_pence, p.expense_account_id, p.counterpart_account_id)
        = (c.evidence_id, c.content_sha256, c.policy_version, c.previous_pence,
           c.amount::numeric * 100, c.expense_account_id, c.counterpart_account_id);
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_saved_expense_journal_amount_correction(uuid,uuid) FROM PUBLIC;
