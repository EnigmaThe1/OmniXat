-- Operator allowlist, not a chart of accounts or a default account mapping.
CREATE TABLE omnixat.expense_counterpart_policy (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    funding_source_id uuid NOT NULL,
    account_id uuid NOT NULL CHECK (account_id <> '00000000-0000-0000-0000-000000000000'),
    eligible_for_drafts boolean NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, organisation_id, funding_source_id, account_id),
    FOREIGN KEY (tenant_id, organisation_id, funding_source_id)
        REFERENCES omnixat.expense_funding_sources(tenant_id, organisation_id, id)
);

ALTER TABLE omnixat.expense_counterpart_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_counterpart_policy FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_counterpart_policy
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_counterpart_policy FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.read_expense_journal_preview(
    organisation uuid, requested_draft uuid, requested_account uuid
)
RETURNS TABLE (
    expense_account_id uuid, counterpart_account_id uuid, funding_source_id uuid,
    amount_pence numeric, currency text, accounting_date date, period_id uuid,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    policy_version text, content_sha256 bytea
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT d.expense_account_id, p.account_id, f.funding_source_id,
           d.amount_pence, d.currency, d.accounting_date, d.period_id,
           d.evidence_id, d.job_id, d.field_name, d.source_row, d.source_column,
           d.policy_version, d.content_sha256
    FROM omnixat_extraction.read_csv_expense_draft(organisation, requested_draft) d
    JOIN omnixat.expense_funding_context f ON f.draft_id = d.draft_id
    JOIN omnixat.expense_funding_sources s
      ON (s.tenant_id, s.organisation_id, s.id, s.payer_id, s.funding_kind) =
         (f.tenant_id, f.organisation_id, f.funding_source_id, f.payer_id, f.funding_kind)
    JOIN omnixat.expense_counterpart_policy p
      ON (p.tenant_id, p.organisation_id, p.funding_source_id) =
         (f.tenant_id, f.organisation_id, f.funding_source_id)
    WHERE f.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND f.organisation_id = organisation AND s.eligible_for_drafts AND p.eligible_for_drafts
      AND p.account_id = requested_account AND p.account_id <> d.expense_account_id;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_preview(uuid,uuid,uuid) FROM PUBLIC;
