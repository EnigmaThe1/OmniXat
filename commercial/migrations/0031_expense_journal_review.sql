CREATE FUNCTION omnixat_extraction.read_expense_journal_draft(organisation uuid, requested_journal uuid)
RETURNS TABLE (
    journal_id uuid, expense_draft_id uuid, journal_created_at timestamptz, journal_created_by text,
    expense_account_id uuid, counterpart_account_id uuid, funding_source_id uuid,
    amount_pence numeric, currency text, accounting_date date, period_id uuid,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    policy_version text, content_sha256 bytea
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT j.id, j.expense_draft_id, j.created_at, j.created_by,
           j.expense_account_id, j.counterpart_account_id, j.funding_source_id,
           j.amount_pence, j.currency, j.accounting_date, j.period_id,
           p.evidence_id, p.job_id, p.field_name, p.source_row, p.source_column,
           j.scan_policy_version, j.content_sha256
    FROM omnixat.expense_journal_drafts j
    CROSS JOIN LATERAL omnixat_extraction.read_expense_journal_preview(
        j.organisation_id, j.expense_draft_id, j.counterpart_account_id
    ) p
    WHERE j.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND j.organisation_id = organisation AND j.id = requested_journal
      AND (j.expense_account_id, j.counterpart_account_id, j.funding_source_id,
           j.amount_pence, j.currency, j.accounting_date, j.period_id,
           j.scan_policy_version, j.content_sha256)
        = (p.expense_account_id, p.counterpart_account_id, p.funding_source_id,
           p.amount_pence, p.currency, p.accounting_date, p.period_id,
           p.policy_version, p.content_sha256);
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_draft(uuid,uuid) FROM PUBLIC;
