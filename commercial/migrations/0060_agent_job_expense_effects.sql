CREATE TABLE omnixat.agent_job_expense_effects (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    expense_id uuid NOT NULL,
    csv_plan_digest bytea NOT NULL CHECK (octet_length(csv_plan_digest) = 32),
    expense_plan_digest bytea NOT NULL CHECK (octet_length(expense_plan_digest) = 32),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, job_id),
    UNIQUE (tenant_id, expense_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_job_expense_plans(tenant_id, job_id),
    FOREIGN KEY (tenant_id, expense_id) REFERENCES omnixat.csv_expense_drafts(tenant_id, id)
);
ALTER TABLE omnixat.agent_job_expense_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_expense_effects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_expense_effects
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_expense_effects FROM PUBLIC;

-- Trusted signed-job boundary: accepts plan digests only, never monetary values.
CREATE FUNCTION omnixat_extraction.create_job_expense_draft(
    job uuid, worker text, lease uuid, expected_csv_plan bytea, expected_expense_plan bytea
)
RETURNS TABLE (expense_id uuid, created_by text, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    plan omnixat.agent_job_expense_plans%ROWTYPE;
    previous omnixat.agent_job_expense_effects%ROWTYPE;
    summary record;
    source_result record;
    expense_result record;
    original_actor text;
BEGIN
    PERFORM 1 FROM omnixat.agent_jobs j WHERE j.tenant_id=tenant AND j.id=job FOR UPDATE;
    PERFORM 1 FROM omnixat.agent_jobs j
    WHERE j.tenant_id=tenant AND j.id=job AND j.status='running'
      AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Live worker claim required' USING ERRCODE='22023';
    END IF;
    SELECT * INTO plan FROM omnixat.agent_job_expense_plans p WHERE p.tenant_id=tenant AND p.job_id=job;
    IF plan.job_id IS NULL OR plan.plan_digest IS DISTINCT FROM expected_expense_plan OR plan.format_version <> 1 THEN
        RAISE EXCEPTION 'Saved expense plan changed or unavailable' USING ERRCODE='22023';
    END IF;
    SELECT * INTO summary FROM omnixat_extraction.read_job_csv_summary(job,worker,lease,expected_csv_plan);
    IF NOT FOUND OR summary.organisation_id <> plan.organisation_id
       OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(summary.cells) cell
                      WHERE cell->>'field_name'=plan.field_name AND cell->'row'=to_jsonb(plan.source_row)
                        AND cell->'column'=to_jsonb(plan.source_column)) THEN
        RAISE EXCEPTION 'Pinned extraction source unavailable' USING ERRCODE='22023';
    END IF;
    SELECT * INTO previous FROM omnixat.agent_job_expense_effects e WHERE e.tenant_id=tenant AND e.job_id=job;
    IF previous.job_id IS NOT NULL AND (
        previous.csv_plan_digest IS DISTINCT FROM expected_csv_plan
        OR previous.expense_plan_digest IS DISTINCT FROM expected_expense_plan) THEN
        RAISE EXCEPTION 'Expense effect inputs changed' USING ERRCODE='22023';
    END IF;
    -- A recovered worker authenticates as itself. Only the persisted first-effect
    -- actor is reused by the shared creators for attribution-preserving replay.
    original_actor := CASE WHEN previous.job_id IS NULL THEN worker ELSE previous.created_by END;
    SELECT * INTO source_result FROM omnixat_extraction.create_csv_draft_amount(
        plan.organisation_id,summary.evidence_id,job,plan.field_name,plan.source_row,plan.source_column,original_actor);
    IF source_result.outcome <> 'stored' THEN
        RAISE EXCEPTION 'Resolved source amount unavailable or conflicting' USING ERRCODE='22023';
    END IF;
    SELECT * INTO expense_result FROM omnixat_extraction.create_csv_expense_draft(
        plan.organisation_id,summary.evidence_id,job,plan.field_name,plan.source_row,plan.source_column,
        plan.period_id,plan.expense_account_id,plan.accounting_date,plan.currency,original_actor);
    IF expense_result.outcome <> 'stored' THEN
        RAISE EXCEPTION 'Expense draft unavailable or conflicting' USING ERRCODE='22023';
    END IF;
    IF previous.job_id IS NOT NULL AND previous.expense_id <> expense_result.draft_id THEN
        RAISE EXCEPTION 'Expense effect receipt changed' USING ERRCODE='22023';
    END IF;
    INSERT INTO omnixat.agent_job_expense_effects
        (tenant_id,job_id,expense_id,csv_plan_digest,expense_plan_digest,created_by)
    VALUES (tenant,job,expense_result.draft_id,expected_csv_plan,expected_expense_plan,original_actor)
    ON CONFLICT (tenant_id,job_id) DO NOTHING;
    PERFORM 1 FROM omnixat.agent_jobs j
    WHERE j.tenant_id=tenant AND j.id=job AND j.status='running'
      AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Claim expired during expense creation' USING ERRCODE='22023';
    END IF;
    RETURN QUERY SELECT e.expense_id,e.created_by,e.created_at
        FROM omnixat.agent_job_expense_effects e WHERE e.tenant_id=tenant AND e.job_id=job;
END;
$$;
REVOKE ALL ON FUNCTION omnixat_extraction.create_job_expense_draft(uuid,text,uuid,bytea,bytea) FROM PUBLIC;
