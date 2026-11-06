-- Internal bookkeeping configuration, not statutory or tax periods.
CREATE TABLE omnixat.expense_accounting_periods (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    open_for_drafts boolean NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, organisation_id) REFERENCES omnixat.organisations(tenant_id, id),
    CHECK (starts_on >= DATE '0001-01-01' AND starts_on <= ends_on AND ends_on <= DATE '9999-12-31')
);

CREATE TABLE omnixat.expense_account_policy (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    account_id uuid NOT NULL CHECK (account_id <> '00000000-0000-0000-0000-000000000000'),
    eligible_for_drafts boolean NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, organisation_id, account_id),
    FOREIGN KEY (tenant_id, organisation_id) REFERENCES omnixat.organisations(tenant_id, id)
);

ALTER TABLE omnixat.expense_accounting_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_accounting_periods FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_accounting_periods
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);

ALTER TABLE omnixat.expense_account_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_account_policy FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_account_policy
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_accounting_periods, omnixat.expense_account_policy FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.read_csv_expense_preview(
    organisation uuid, evidence uuid, job uuid, requested_field text,
    requested_row integer, requested_column integer, period uuid, account uuid,
    accounting_date date
)
RETURNS TABLE (period_start date, period_end date, amount text, source_kind text,
               created_by text, created_at timestamptz, policy_version text, content_sha256 bytea)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT p.starts_on, p.ends_on, d.amount, d.source_kind, d.created_by, d.created_at,
           d.policy_version, d.content_sha256
    FROM omnixat.expense_accounting_periods p
    JOIN omnixat.expense_account_policy a USING (tenant_id, organisation_id)
    LEFT JOIN LATERAL omnixat_extraction.read_csv_draft_amount(
        organisation, evidence, job, requested_field, requested_row, requested_column
    ) d ON true
    WHERE p.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND p.organisation_id = organisation AND p.id = period AND p.open_for_drafts
      AND a.account_id = account AND a.eligible_for_drafts
      AND accounting_date BETWEEN p.starts_on AND p.ends_on;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_csv_expense_preview(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date)
    FROM PUBLIC;
