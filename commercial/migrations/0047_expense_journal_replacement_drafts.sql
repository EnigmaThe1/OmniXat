ALTER TABLE omnixat.expense_journal_amount_correction_decisions
    ADD UNIQUE (tenant_id, organisation_id, proposal_id, proposal_sha256, reviewer_id, decision);

CREATE TABLE omnixat.expense_journal_replacements (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    original_journal_id uuid NOT NULL,
    original_snapshot_sha256 bytea NOT NULL CHECK (octet_length(original_snapshot_sha256) = 32),
    proposal_id uuid NOT NULL,
    proposal_sha256 bytea NOT NULL CHECK (octet_length(proposal_sha256) = 32),
    reviewer_id text NOT NULL,
    review_decision text NOT NULL DEFAULT 'reviewed' CHECK (review_decision = 'reviewed'),
    reviewed_at timestamptz NOT NULL,
    accounting_date date NOT NULL,
    period_id uuid NOT NULL,
    funding_source_id uuid NOT NULL,
    expense_account_id uuid NOT NULL,
    counterpart_account_id uuid NOT NULL CHECK (counterpart_account_id <> expense_account_id),
    amount_pence numeric NOT NULL CHECK (
        amount_pence >= 1 AND amount_pence < 100000000000000000000 AND amount_pence = trunc(amount_pence)
    ),
    currency text NOT NULL CHECK (currency = 'GBP'),
    evidence_id uuid NOT NULL,
    job_id uuid NOT NULL,
    field_name text NOT NULL,
    source_row integer NOT NULL CHECK (source_row BETWEEN 1 AND 5000),
    source_column integer NOT NULL CHECK (source_column BETWEEN 1 AND 64),
    content_sha256 bytea NOT NULL,
    scan_policy_version text NOT NULL,
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, original_journal_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, organisation_id, original_journal_id)
        REFERENCES omnixat.expense_journal_drafts (tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, organisation_id, proposal_id, proposal_sha256, reviewer_id, review_decision)
        REFERENCES omnixat.expense_journal_amount_correction_decisions
            (tenant_id, organisation_id, proposal_id, proposal_sha256, reviewer_id, decision),
    FOREIGN KEY (tenant_id, organisation_id, evidence_id, content_sha256)
        REFERENCES omnixat.evidence_registrations (tenant_id, organisation_id, id, content_sha256),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.csv_extraction_results (tenant_id, job_id)
);

ALTER TABLE omnixat.expense_journal_replacements ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_replacements FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_replacements
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_replacements FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.create_expense_journal_replacement(
    organisation uuid, requested_proposal uuid, expected_proposal bytea, requested_reviewer text, actor_id text
)
RETURNS TABLE (outcome text, replacement_id uuid, original_journal uuid, recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    saved_proposal omnixat.expense_journal_amount_corrections%ROWTYPE;
    checked record;
    candidate record;
    previous omnixat.expense_journal_replacements%ROWTYPE;
BEGIN
    SELECT p.* INTO saved_proposal FROM omnixat.expense_journal_amount_corrections p
    WHERE p.tenant_id = tenant AND p.organisation_id = organisation AND p.id = requested_proposal
    FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    -- The proposal exists and is locked. Replaying its original inputs cannot
    -- create or alter it, and reuses the writer's source/policy locks.
    SELECT * INTO checked FROM omnixat_extraction.create_expense_journal_amount_correction(
        organisation, saved_proposal.journal_id, saved_proposal.snapshot_sha256, saved_proposal.job_id,
        saved_proposal.field_name, saved_proposal.source_row, saved_proposal.source_column,
        saved_proposal.currency, saved_proposal.created_by
    );
    IF checked.outcome <> 'stored' OR checked.proposal_id IS DISTINCT FROM requested_proposal THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    PERFORM 1 FROM omnixat.expense_journal_amount_correction_decisions d
    WHERE d.tenant_id = tenant AND d.organisation_id = organisation AND d.proposal_id = requested_proposal
      AND d.proposal_sha256 = expected_proposal AND d.reviewer_id = requested_reviewer AND d.decision = 'reviewed'
    FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    SELECT * INTO candidate FROM omnixat_extraction.read_expense_journal_replacement_preview(
        organisation, requested_proposal, expected_proposal, requested_reviewer
    );
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_replacements (
        tenant_id, organisation_id, original_journal_id, original_snapshot_sha256,
        proposal_id, proposal_sha256, reviewer_id, reviewed_at, accounting_date, period_id,
        funding_source_id, expense_account_id, counterpart_account_id, amount_pence, currency,
        evidence_id, job_id, field_name, source_row, source_column, content_sha256, scan_policy_version, created_by
    ) VALUES (
        tenant, organisation, candidate.journal_id, candidate.snapshot_sha256,
        candidate.proposal_id, candidate.proposal_sha256, candidate.reviewer_id, candidate.reviewed_at,
        candidate.accounting_date, candidate.period_id, candidate.funding_source_id,
        candidate.expense_account_id, candidate.counterpart_account_id, candidate.amount::numeric * 100, 'GBP',
        candidate.evidence_id, candidate.job_id, candidate.field_name, candidate.source_row, candidate.source_column,
        candidate.content_sha256, candidate.policy_version, actor_id
    ) ON CONFLICT DO NOTHING;

    SELECT r.* INTO STRICT previous FROM omnixat.expense_journal_replacements r
    WHERE r.tenant_id = tenant AND r.original_journal_id = candidate.journal_id;
    IF (previous.organisation_id, previous.original_snapshot_sha256, previous.proposal_id,
        previous.proposal_sha256, previous.reviewer_id, previous.reviewed_at, previous.accounting_date,
        previous.period_id, previous.funding_source_id, previous.expense_account_id,
        previous.counterpart_account_id, previous.amount_pence, previous.evidence_id, previous.job_id,
        previous.field_name, previous.source_row, previous.source_column, previous.content_sha256,
        previous.scan_policy_version, previous.created_by)
       IS DISTINCT FROM (organisation, candidate.snapshot_sha256, candidate.proposal_id,
        candidate.proposal_sha256, candidate.reviewer_id, candidate.reviewed_at, candidate.accounting_date,
        candidate.period_id, candidate.funding_source_id, candidate.expense_account_id,
        candidate.counterpart_account_id, candidate.amount::numeric * 100, candidate.evidence_id, candidate.job_id,
        candidate.field_name, candidate.source_row, candidate.source_column, candidate.content_sha256,
        candidate.policy_version, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::uuid, NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.id, previous.original_journal_id, previous.created_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.create_expense_journal_replacement(uuid,uuid,bytea,text,text) FROM PUBLIC;
