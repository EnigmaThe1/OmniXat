CREATE TABLE omnixat.expense_journal_amount_corrections (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    journal_id uuid NOT NULL,
    snapshot_sha256 bytea NOT NULL CHECK (octet_length(snapshot_sha256) = 32),
    reason text NOT NULL DEFAULT 'amount' CHECK (reason = 'amount'),
    evidence_id uuid NOT NULL,
    job_id uuid NOT NULL,
    field_name text NOT NULL,
    source_row integer NOT NULL CHECK (source_row BETWEEN 1 AND 5000),
    source_column integer NOT NULL CHECK (source_column BETWEEN 1 AND 64),
    content_sha256 bytea NOT NULL,
    scan_policy_version text NOT NULL,
    previous_pence numeric NOT NULL CHECK (previous_pence >= 1 AND previous_pence = trunc(previous_pence)),
    proposed_pence numeric NOT NULL CHECK (
        proposed_pence >= 1 AND proposed_pence < 100000000000000000000 AND proposed_pence = trunc(proposed_pence)
    ),
    expense_account_id uuid NOT NULL,
    counterpart_account_id uuid NOT NULL CHECK (counterpart_account_id <> expense_account_id),
    currency text NOT NULL CHECK (currency = 'GBP'),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, journal_id, snapshot_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, organisation_id, journal_id)
        REFERENCES omnixat.expense_journal_drafts (tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, journal_id, snapshot_sha256, reason)
        REFERENCES omnixat.expense_journal_clarification_evidence (tenant_id, journal_id, snapshot_sha256, reason),
    FOREIGN KEY (tenant_id, organisation_id, evidence_id, content_sha256)
        REFERENCES omnixat.evidence_registrations (tenant_id, organisation_id, id, content_sha256),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.csv_extraction_results (tenant_id, job_id)
);

ALTER TABLE omnixat.expense_journal_amount_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_amount_corrections FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_amount_corrections
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_amount_corrections FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.create_expense_journal_amount_correction(
    organisation uuid, requested_journal uuid, expected_snapshot bytea, requested_job uuid,
    requested_field text, requested_row integer, requested_column integer, confirmed_currency text, actor_id text
)
RETURNS TABLE (outcome text, proposal_id uuid, recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    active_policy text;
    source_evidence uuid;
    supporting_evidence uuid;
    source_job uuid;
    source_field text;
    candidate record;
    proposed numeric;
    previous omnixat.expense_journal_amount_corrections%ROWTYPE;
BEGIN
    SELECT p.policy_version INTO active_policy FROM omnixat_extraction.active_scan_policy p FOR SHARE;
    IF active_policy IS NULL OR confirmed_currency IS DISTINCT FROM 'GBP' THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    -- Stabilise the saved journal and the policies that make it eligible.
    SELECT d.evidence_id, l.evidence_id, d.job_id, d.field_name
    INTO source_evidence, supporting_evidence, source_job, source_field
    FROM omnixat.expense_journal_drafts j
    JOIN omnixat.csv_expense_drafts d
      ON (d.tenant_id, d.organisation_id, d.id) = (j.tenant_id, j.organisation_id, j.expense_draft_id)
    JOIN omnixat.expense_accounting_periods p
      ON (p.tenant_id, p.organisation_id, p.id) = (d.tenant_id, d.organisation_id, d.period_id)
    JOIN omnixat.expense_account_policy a
      ON (a.tenant_id, a.organisation_id, a.account_id) = (d.tenant_id, d.organisation_id, d.expense_account_id)
    JOIN omnixat.expense_funding_context f
      ON (f.tenant_id, f.organisation_id, f.draft_id) = (d.tenant_id, d.organisation_id, d.id)
    JOIN omnixat.expense_funding_sources s
      ON (s.tenant_id, s.organisation_id, s.id) = (f.tenant_id, f.organisation_id, f.funding_source_id)
    JOIN omnixat.expense_counterpart_policy c
      ON (c.tenant_id, c.organisation_id, c.funding_source_id, c.account_id) =
         (s.tenant_id, s.organisation_id, s.id, j.counterpart_account_id)
    JOIN omnixat.expense_journal_clarification_evidence l
      ON (l.tenant_id, l.organisation_id, l.journal_id, l.snapshot_sha256, l.reason) =
         (j.tenant_id, j.organisation_id, j.id, expected_snapshot, 'amount')
    WHERE j.tenant_id = tenant AND j.organisation_id = organisation AND j.id = requested_journal
      AND p.open_for_drafts AND a.eligible_for_drafts AND s.eligible_for_drafts AND c.eligible_for_drafts
    FOR SHARE OF j, d, p, a, f, s, c, l;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    -- Lock both originals in a stable order before scan claims and extraction rows.
    PERFORM 1 FROM omnixat.evidence_quarantine q
    JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
    WHERE q.tenant_id = tenant AND r.organisation_id = organisation
      AND q.evidence_id IN (source_evidence, supporting_evidence)
    ORDER BY q.evidence_id
    FOR UPDATE OF q FOR SHARE OF r;

    PERFORM 1 FROM omnixat.evidence_scan_claims c
    WHERE c.tenant_id = tenant AND c.policy_version = active_policy
      AND c.evidence_id IN (source_evidence, supporting_evidence)
    ORDER BY c.evidence_id FOR SHARE NOWAIT;

    PERFORM 1 FROM omnixat.csv_extraction_results r
    WHERE r.tenant_id = tenant AND r.job_id IN (source_job, requested_job)
    ORDER BY r.job_id FOR SHARE;
    PERFORM 1 FROM omnixat.evidence_draft_amounts a
    WHERE a.tenant_id = tenant AND a.job_id = source_job AND a.field_name = source_field
    FOR SHARE;

    SELECT * INTO candidate FROM omnixat_extraction.read_expense_journal_amount_correction(
        organisation, requested_journal, expected_snapshot, requested_job,
        requested_field, requested_row, requested_column
    );
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;
    proposed := candidate.amount::numeric * 100;
    IF proposed < 1 OR proposed >= 100000000000000000000 OR proposed <> trunc(proposed) THEN
        RETURN QUERY SELECT 'invalid_amount'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_amount_corrections (
        tenant_id, organisation_id, journal_id, snapshot_sha256, evidence_id, job_id,
        field_name, source_row, source_column, content_sha256, scan_policy_version,
        previous_pence, proposed_pence, expense_account_id, counterpart_account_id, currency, created_by
    ) VALUES (
        tenant, organisation, requested_journal, expected_snapshot, candidate.evidence_id, requested_job,
        requested_field, requested_row, requested_column, candidate.content_sha256, candidate.policy_version,
        candidate.previous_pence, proposed, candidate.expense_account_id, candidate.counterpart_account_id, 'GBP', actor_id
    ) ON CONFLICT DO NOTHING;

    SELECT r.* INTO STRICT previous FROM omnixat.expense_journal_amount_corrections r
    WHERE r.tenant_id = tenant AND r.journal_id = requested_journal AND r.snapshot_sha256 = expected_snapshot;
    IF (previous.organisation_id, previous.evidence_id, previous.job_id, previous.field_name,
        previous.source_row, previous.source_column, previous.content_sha256, previous.scan_policy_version,
        previous.previous_pence, previous.proposed_pence, previous.expense_account_id,
        previous.counterpart_account_id, previous.created_by)
       IS DISTINCT FROM (organisation, candidate.evidence_id, requested_job, requested_field,
        requested_row, requested_column, candidate.content_sha256, candidate.policy_version,
        candidate.previous_pence, proposed, candidate.expense_account_id, candidate.counterpart_account_id, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.id, previous.created_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.create_expense_journal_amount_correction(uuid,uuid,bytea,uuid,text,integer,integer,text,text)
    FROM PUBLIC;
