CREATE FUNCTION omnixat_extraction.read_csv_expense_draft(organisation uuid, requested_draft uuid)
RETURNS TABLE (
    draft_id uuid, expense_created_at timestamptz, expense_created_by text,
    amount_pence numeric, currency text, accounting_date date, expense_account_id uuid, period_id uuid,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    amount text, source_kind text, created_by text, created_at timestamptz,
    policy_version text, content_sha256 bytea
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT d.id, d.created_at, d.created_by, d.amount_pence, d.currency, d.accounting_date,
           d.expense_account_id, d.period_id, d.evidence_id, d.job_id, d.field_name, a.source_row,
           a.source_column, p.amount, p.source_kind, p.created_by, p.created_at,
           p.policy_version, p.content_sha256
    FROM omnixat.csv_expense_drafts d
    JOIN omnixat.evidence_draft_amounts a USING (tenant_id, job_id, field_name)
    CROSS JOIN LATERAL omnixat_extraction.read_csv_expense_preview(
        d.organisation_id, d.evidence_id, d.job_id, d.field_name, a.source_row, a.source_column,
        d.period_id, d.expense_account_id, d.accounting_date
    ) p
    WHERE d.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND d.organisation_id = organisation AND d.id = requested_draft
      AND d.currency = 'GBP' AND d.amount_pence = p.amount::numeric * 100;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_csv_expense_draft(uuid,uuid) FROM PUBLIC;
