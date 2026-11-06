ALTER TABLE omnixat.expense_journal_drafts ADD UNIQUE (tenant_id, organisation_id, id);

CREATE TABLE omnixat.expense_journal_review_decisions (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    journal_id uuid NOT NULL,
    snapshot_sha256 bytea NOT NULL CHECK (octet_length(snapshot_sha256) = 32),
    reviewer_id text NOT NULL CHECK (char_length(reviewer_id) BETWEEN 1 AND 200 AND btrim(reviewer_id) <> ''),
    decision text NOT NULL CHECK (decision IN ('reviewed', 'changes_requested')),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, journal_id, snapshot_sha256, reviewer_id),
    FOREIGN KEY (tenant_id, organisation_id, journal_id)
        REFERENCES omnixat.expense_journal_drafts(tenant_id, organisation_id, id)
);

ALTER TABLE omnixat.expense_journal_review_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_review_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_review_decisions
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_review_decisions FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.read_expense_journal_review(organisation uuid, requested_journal uuid)
RETURNS TABLE (
    journal_id uuid, expense_draft_id uuid, journal_created_at timestamptz, journal_created_by text,
    expense_account_id uuid, counterpart_account_id uuid, funding_source_id uuid,
    amount_pence numeric, currency text, accounting_date date, period_id uuid,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    policy_version text, content_sha256 bytea, snapshot_sha256 bytea
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT j.*, sha256(convert_to(jsonb_build_array(
        'expense-journal-review-v1',
        NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid, organisation,
        j.journal_id, j.expense_draft_id, extract(epoch FROM j.journal_created_at), j.journal_created_by,
        'debit', j.expense_account_id, 'credit', j.counterpart_account_id, j.funding_source_id,
        trunc(j.amount_pence), j.currency, j.accounting_date - DATE '2000-01-01', j.period_id,
        j.evidence_id, j.job_id, j.field_name, j.source_row, j.source_column,
        j.policy_version, encode(j.content_sha256, 'hex')
    )::text, 'UTF8'))
    FROM omnixat_extraction.read_expense_journal_draft(organisation, requested_journal) j;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_review(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.record_expense_journal_decision(
    organisation uuid, requested_journal uuid, expected_snapshot bytea, requested_decision text, actor_id text
)
RETURNS TABLE (outcome text, decision_recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    current_snapshot bytea;
    stored_decision text;
    stored_at timestamptz;
BEGIN
    SELECT j.snapshot_sha256 INTO current_snapshot
    FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j;
    IF current_snapshot IS NULL OR current_snapshot IS DISTINCT FROM expected_snapshot THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_review_decisions
        (tenant_id, organisation_id, journal_id, snapshot_sha256, reviewer_id, decision)
    VALUES (tenant, organisation, requested_journal, current_snapshot, actor_id, requested_decision)
    ON CONFLICT (tenant_id, journal_id, snapshot_sha256, reviewer_id) DO NOTHING;

    SELECT d.decision, d.recorded_at INTO STRICT stored_decision, stored_at
    FROM omnixat.expense_journal_review_decisions d
    WHERE d.tenant_id = tenant AND d.organisation_id = organisation AND d.journal_id = requested_journal
      AND d.snapshot_sha256 = current_snapshot AND d.reviewer_id = actor_id;
    IF stored_decision IS DISTINCT FROM requested_decision THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, stored_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.record_expense_journal_decision(uuid,uuid,bytea,text,text) FROM PUBLIC;
