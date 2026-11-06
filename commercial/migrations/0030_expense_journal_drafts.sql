-- One amount represents both sides of this bounded two-line journal draft.
CREATE TABLE omnixat.expense_journal_drafts (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    expense_draft_id uuid NOT NULL,
    funding_source_id uuid NOT NULL,
    expense_account_id uuid NOT NULL,
    counterpart_account_id uuid NOT NULL CHECK (counterpart_account_id <> expense_account_id),
    amount_pence numeric NOT NULL CHECK (
        amount_pence >= 1 AND amount_pence < 100000000000000000000 AND amount_pence = trunc(amount_pence)
    ),
    currency text NOT NULL CHECK (currency = 'GBP'),
    accounting_date date NOT NULL,
    period_id uuid NOT NULL,
    scan_policy_version text NOT NULL,
    content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, expense_draft_id),
    FOREIGN KEY (tenant_id, organisation_id, expense_draft_id)
        REFERENCES omnixat.csv_expense_drafts(tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, organisation_id, funding_source_id, counterpart_account_id)
        REFERENCES omnixat.expense_counterpart_policy(tenant_id, organisation_id, funding_source_id, account_id),
    FOREIGN KEY (tenant_id, organisation_id, expense_account_id)
        REFERENCES omnixat.expense_account_policy(tenant_id, organisation_id, account_id),
    FOREIGN KEY (tenant_id, organisation_id, period_id)
        REFERENCES omnixat.expense_accounting_periods(tenant_id, organisation_id, id)
);

ALTER TABLE omnixat.expense_journal_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_drafts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_drafts
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_drafts FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.create_expense_journal_draft(
    organisation uuid, requested_draft uuid, requested_account uuid, actor_id text
)
RETURNS TABLE (outcome text, journal_id uuid, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    active_policy text;
    evidence uuid;
    candidate record;
    previous omnixat.expense_journal_drafts%ROWTYPE;
BEGIN
    SELECT p.policy_version INTO active_policy
    FROM omnixat_extraction.active_scan_policy p FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    SELECT d.evidence_id INTO evidence
    FROM omnixat.csv_expense_drafts d
    JOIN omnixat.expense_accounting_periods p
      ON (p.tenant_id, p.organisation_id, p.id) = (d.tenant_id, d.organisation_id, d.period_id)
    JOIN omnixat.expense_account_policy a
      ON (a.tenant_id, a.organisation_id, a.account_id) = (d.tenant_id, d.organisation_id, d.expense_account_id)
    JOIN omnixat.expense_funding_context f
      ON (f.tenant_id, f.organisation_id, f.draft_id) = (d.tenant_id, d.organisation_id, d.id)
    JOIN omnixat.expense_funding_sources s
      ON (s.tenant_id, s.organisation_id, s.id) = (f.tenant_id, f.organisation_id, f.funding_source_id)
    JOIN omnixat.expense_counterpart_policy c
      ON (c.tenant_id, c.organisation_id, c.funding_source_id) = (s.tenant_id, s.organisation_id, s.id)
    WHERE d.tenant_id = tenant AND d.organisation_id = organisation AND d.id = requested_draft
      AND p.open_for_drafts AND a.eligible_for_drafts AND s.eligible_for_drafts AND c.eligible_for_drafts
      AND c.account_id = requested_account AND c.account_id <> d.expense_account_id
    FOR SHARE OF d, p, a, f, s, c;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    -- Match the expense writer's quarantine/scan-claim lock order.
    PERFORM 1 FROM omnixat.evidence_quarantine q
    JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
    WHERE q.tenant_id = tenant AND q.evidence_id = evidence AND r.organisation_id = organisation
    FOR UPDATE OF q FOR SHARE OF r;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;
    PERFORM 1 FROM omnixat.evidence_scan_claims c
    WHERE c.tenant_id = tenant AND c.evidence_id = evidence AND c.policy_version = active_policy
    FOR SHARE NOWAIT;

    -- Keep the source amount and extraction record stable as well.
    PERFORM 1 FROM omnixat.csv_expense_drafts d
    JOIN omnixat.evidence_draft_amounts a USING (tenant_id, job_id, field_name)
    JOIN omnixat.csv_extraction_results r ON (r.tenant_id, r.job_id) = (d.tenant_id, d.job_id)
    WHERE d.tenant_id = tenant AND d.organisation_id = organisation AND d.id = requested_draft
    FOR SHARE OF a, r;

    SELECT * INTO candidate FROM omnixat_extraction.read_expense_journal_preview(
        organisation, requested_draft, requested_account
    );
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_drafts (
        tenant_id, organisation_id, expense_draft_id, funding_source_id, expense_account_id,
        counterpart_account_id, amount_pence, currency, accounting_date, period_id,
        scan_policy_version, content_sha256, created_by
    ) VALUES (
        tenant, organisation, requested_draft, candidate.funding_source_id, candidate.expense_account_id,
        candidate.counterpart_account_id, candidate.amount_pence, candidate.currency,
        candidate.accounting_date, candidate.period_id, candidate.policy_version, candidate.content_sha256, actor_id
    ) ON CONFLICT (tenant_id, expense_draft_id) DO NOTHING;

    SELECT j.* INTO STRICT previous FROM omnixat.expense_journal_drafts j
    WHERE j.tenant_id = tenant AND j.expense_draft_id = requested_draft;
    IF (previous.organisation_id, previous.funding_source_id, previous.expense_account_id,
        previous.counterpart_account_id, previous.amount_pence, previous.currency, previous.accounting_date,
        previous.period_id, previous.scan_policy_version, previous.content_sha256, previous.created_by)
       IS DISTINCT FROM (organisation, candidate.funding_source_id, candidate.expense_account_id,
        candidate.counterpart_account_id, candidate.amount_pence, candidate.currency, candidate.accounting_date,
        candidate.period_id, candidate.policy_version, candidate.content_sha256, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.id, previous.created_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.create_expense_journal_draft(uuid,uuid,uuid,text) FROM PUBLIC;
