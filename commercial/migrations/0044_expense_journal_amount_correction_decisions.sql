ALTER TABLE omnixat.expense_journal_amount_corrections ADD UNIQUE (tenant_id, organisation_id, id);

CREATE TABLE omnixat.expense_journal_amount_correction_decisions (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    proposal_sha256 bytea NOT NULL CHECK (octet_length(proposal_sha256) = 32),
    reviewer_id text NOT NULL CHECK (char_length(reviewer_id) BETWEEN 1 AND 200 AND btrim(reviewer_id) <> ''),
    decision text NOT NULL CHECK (decision IN ('reviewed', 'changes_requested')),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, proposal_id, proposal_sha256, reviewer_id),
    FOREIGN KEY (tenant_id, organisation_id, proposal_id)
        REFERENCES omnixat.expense_journal_amount_corrections (tenant_id, organisation_id, id)
);

ALTER TABLE omnixat.expense_journal_amount_correction_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_amount_correction_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_amount_correction_decisions
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_amount_correction_decisions FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.read_expense_journal_amount_correction_review(
    organisation uuid, requested_proposal uuid
)
RETURNS TABLE (
    proposal_id uuid, journal_id uuid, snapshot_sha256 bytea, created_by text, created_at timestamptz,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    content_sha256 bytea, policy_version text, amount text, previous_pence numeric,
    expense_account_id uuid, counterpart_account_id uuid, proposal_sha256 bytea
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT p.*, sha256(convert_to(jsonb_build_array(
        'expense-journal-amount-correction-review-v1',
        NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid, organisation,
        p.proposal_id, p.journal_id, encode(p.snapshot_sha256, 'hex'),
        p.created_by, extract(epoch FROM p.created_at),
        p.evidence_id, p.job_id, p.field_name, p.source_row, p.source_column,
        encode(p.content_sha256, 'hex'), p.policy_version, 'GBP', trunc(p.previous_pence),
        'debit', p.expense_account_id, 'credit', p.counterpart_account_id, trunc(p.amount::numeric * 100)
    )::text, 'UTF8'))
    FROM omnixat_extraction.read_saved_expense_journal_amount_correction(organisation, requested_proposal) p;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_amount_correction_review(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.record_expense_journal_amount_correction_decision(
    organisation uuid, requested_proposal uuid, expected_proposal bytea, requested_decision text, actor_id text
)
RETURNS TABLE (outcome text, decision_recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    current_digest bytea;
    stored_decision text;
    stored_at timestamptz;
BEGIN
    PERFORM 1 FROM omnixat.expense_journal_amount_corrections p
    WHERE p.tenant_id = tenant AND p.organisation_id = organisation AND p.id = requested_proposal
    FOR SHARE;

    SELECT p.proposal_sha256 INTO current_digest
    FROM omnixat_extraction.read_expense_journal_amount_correction_review(organisation, requested_proposal) p;
    IF current_digest IS NULL OR current_digest IS DISTINCT FROM expected_proposal THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_amount_correction_decisions
        (tenant_id, organisation_id, proposal_id, proposal_sha256, reviewer_id, decision)
    VALUES (tenant, organisation, requested_proposal, current_digest, actor_id, requested_decision)
    ON CONFLICT DO NOTHING;

    SELECT d.decision, d.recorded_at INTO STRICT stored_decision, stored_at
    FROM omnixat.expense_journal_amount_correction_decisions d
    WHERE d.tenant_id = tenant AND d.organisation_id = organisation AND d.proposal_id = requested_proposal
      AND d.proposal_sha256 = current_digest AND d.reviewer_id = actor_id;
    IF stored_decision IS DISTINCT FROM requested_decision THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, stored_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.record_expense_journal_amount_correction_decision(uuid,uuid,bytea,text,text)
    FROM PUBLIC;
