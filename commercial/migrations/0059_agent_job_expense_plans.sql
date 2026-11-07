ALTER TABLE omnixat.agent_job_evidence_tasks
    ADD UNIQUE (tenant_id, job_id, organisation_id);

CREATE TABLE omnixat.agent_job_expense_plans (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    format_version integer NOT NULL DEFAULT 1 CHECK (format_version = 1),
    field_name text NOT NULL CHECK (field_name COLLATE "C" ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_row integer NOT NULL CHECK (source_row BETWEEN 1 AND 5000),
    source_column integer NOT NULL CHECK (source_column BETWEEN 1 AND 64),
    currency text NOT NULL CHECK (currency = 'GBP'),
    accounting_date date NOT NULL CHECK (accounting_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    period_id uuid NOT NULL,
    expense_account_id uuid NOT NULL,
    plan_digest bytea NOT NULL CHECK (octet_length(plan_digest) = 32),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_job_csv_plans(tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id, organisation_id)
        REFERENCES omnixat.agent_job_evidence_tasks(tenant_id, job_id, organisation_id),
    FOREIGN KEY (tenant_id, organisation_id, period_id)
        REFERENCES omnixat.expense_accounting_periods(tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, organisation_id, expense_account_id)
        REFERENCES omnixat.expense_account_policy(tenant_id, organisation_id, account_id)
);
ALTER TABLE omnixat.agent_job_expense_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_expense_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_expense_plans
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_expense_plans FROM PUBLIC;
