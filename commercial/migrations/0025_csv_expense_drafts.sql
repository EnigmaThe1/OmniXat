CREATE TABLE omnixat.csv_expense_drafts (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    organisation_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    job_id uuid NOT NULL,
    field_name text NOT NULL,
    period_id uuid NOT NULL,
    expense_account_id uuid NOT NULL,
    accounting_date date NOT NULL,
    currency text NOT NULL CHECK (currency = 'GBP'),
    amount_pence numeric NOT NULL CHECK (
        amount_pence >= 1 AND amount_pence < 100000000000000000000
        AND amount_pence = trunc(amount_pence)
    ),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, job_id, field_name),
    FOREIGN KEY (tenant_id, job_id, field_name) REFERENCES omnixat.evidence_draft_amounts(tenant_id, job_id, field_name),
    FOREIGN KEY (tenant_id, evidence_id) REFERENCES omnixat.evidence_quarantine(tenant_id, evidence_id),
    FOREIGN KEY (tenant_id, organisation_id, period_id)
        REFERENCES omnixat.expense_accounting_periods(tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, organisation_id, expense_account_id)
        REFERENCES omnixat.expense_account_policy(tenant_id, organisation_id, account_id)
);

ALTER TABLE omnixat.csv_expense_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.csv_expense_drafts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.csv_expense_drafts
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.csv_expense_drafts FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.create_csv_expense_draft(
    organisation uuid, evidence uuid, job uuid, requested_field text,
    requested_row integer, requested_column integer, period uuid, account uuid,
    requested_date date, currency_code text, actor_id text
)
RETURNS TABLE (outcome text, draft_id uuid, stored_at timestamptz, stored_pence numeric)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    active_policy text;
    source_amount text;
    pence numeric;
    previous omnixat.csv_expense_drafts%ROWTYPE;
BEGIN
    SELECT p.policy_version INTO active_policy
    FROM omnixat_extraction.active_scan_policy p FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::uuid, NULL::timestamptz, NULL::numeric;
        RETURN;
    END IF;

    PERFORM 1 FROM omnixat.expense_accounting_periods p
    JOIN omnixat.expense_account_policy a USING (tenant_id, organisation_id)
    WHERE p.tenant_id = tenant AND p.organisation_id = organisation
      AND p.id = period AND p.open_for_drafts AND requested_date BETWEEN p.starts_on AND p.ends_on
      AND a.account_id = account AND a.eligible_for_drafts AND currency_code = 'GBP'
    FOR SHARE OF p, a;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'context'::text, NULL::uuid, NULL::timestamptz, NULL::numeric;
        RETURN;
    END IF;

    -- The non-deferrable claim/verdict foreign keys take KEY SHARE here.
    -- Prevent new observations until commit, then lock any existing claim
    -- against expiry renewal. NOWAIT avoids reversing a finishing scanner's
    -- claim/parent lock order; the caller can safely retry the whole operation.
    PERFORM 1 FROM omnixat.evidence_quarantine q
    JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
    WHERE q.tenant_id = tenant AND q.evidence_id = evidence AND r.organisation_id = organisation
    FOR UPDATE OF q;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::uuid, NULL::timestamptz, NULL::numeric;
        RETURN;
    END IF;
    PERFORM 1 FROM omnixat.evidence_scan_claims c
    WHERE c.tenant_id = tenant AND c.evidence_id = evidence AND c.policy_version = active_policy
    FOR SHARE NOWAIT;

    SELECT d.amount INTO source_amount
    FROM omnixat_extraction.read_csv_draft_amount(
        organisation, evidence, job, requested_field, requested_row, requested_column
    ) d;
    IF source_amount IS NULL THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::uuid, NULL::timestamptz, NULL::numeric;
        RETURN;
    END IF;
    pence := source_amount::numeric * 100;
    IF pence < 1 OR pence >= 100000000000000000000 OR pence <> trunc(pence) THEN
        RETURN QUERY SELECT 'amount'::text, NULL::uuid, NULL::timestamptz, NULL::numeric;
        RETURN;
    END IF;

    INSERT INTO omnixat.csv_expense_drafts
        (tenant_id, organisation_id, evidence_id, job_id, field_name, period_id,
         expense_account_id, accounting_date, currency, amount_pence, created_by)
    VALUES (tenant, organisation, evidence, job, requested_field, period,
            account, requested_date, currency_code, trunc(pence), actor_id)
    ON CONFLICT (tenant_id, job_id, field_name) DO NOTHING;

    SELECT * INTO STRICT previous FROM omnixat.csv_expense_drafts d
    WHERE d.tenant_id = tenant AND d.job_id = job AND d.field_name = requested_field;
    IF (previous.organisation_id, previous.evidence_id, previous.period_id, previous.expense_account_id,
        previous.accounting_date, previous.currency, previous.amount_pence, previous.created_by)
       IS DISTINCT FROM (organisation, evidence, period, account, requested_date, currency_code, pence, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::uuid, NULL::timestamptz, NULL::numeric;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.id, previous.created_at, previous.amount_pence;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.create_csv_expense_draft(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date,text,text)
    FROM PUBLIC;
