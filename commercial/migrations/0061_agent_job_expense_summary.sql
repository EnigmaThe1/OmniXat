-- Read-only recovery: monetary values are checked inside the shared read gate,
-- then redacted before this function returns to its execute-only caller.
CREATE FUNCTION omnixat_extraction.read_job_expense_summary(
    job uuid, worker text, lease uuid, expected_csv_plan bytea, expected_expense_plan bytea
)
RETURNS TABLE (expense_id uuid, created_by text, created_at timestamptz,
    expense_created_at timestamptz, organisation_id uuid, evidence_id uuid,
    content_sha256 bytea, policy_version text, source_kind text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    plan omnixat.agent_job_expense_plans%ROWTYPE;
    effect omnixat.agent_job_expense_effects%ROWTYPE;
    source record;
    expense record;
BEGIN
    SELECT * INTO plan FROM omnixat.agent_job_expense_plans p WHERE p.tenant_id=tenant AND p.job_id=job;
    IF NOT FOUND OR plan.plan_digest IS DISTINCT FROM expected_expense_plan OR plan.format_version <> 1 THEN RETURN; END IF;
    SELECT * INTO effect FROM omnixat.agent_job_expense_effects e WHERE e.tenant_id=tenant AND e.job_id=job;
    IF NOT FOUND OR effect.csv_plan_digest IS DISTINCT FROM expected_csv_plan
       OR effect.expense_plan_digest IS DISTINCT FROM expected_expense_plan THEN RETURN; END IF;

    -- This shared metadata gate checks current worker/token/lease, task source,
    -- original extraction effect, ordered CSV plan, scan policy and answer shapes.
    SELECT * INTO source FROM omnixat_extraction.read_job_csv_summary(job,worker,lease,expected_csv_plan);
    IF NOT FOUND OR source.organisation_id <> plan.organisation_id THEN RETURN; END IF;
    SELECT * INTO expense FROM omnixat_extraction.read_csv_expense_draft(plan.organisation_id,effect.expense_id);
    IF NOT FOUND THEN RETURN; END IF;
    IF (expense.job_id,expense.evidence_id,expense.content_sha256,
        expense.field_name,expense.source_row,expense.source_column,
        expense.currency,expense.accounting_date,expense.period_id,expense.expense_account_id,
        expense.expense_created_by,expense.created_by,expense.policy_version)
       IS DISTINCT FROM
       (job,source.evidence_id,source.content_sha256,
        plan.field_name,plan.source_row,plan.source_column,
        plan.currency,plan.accounting_date,plan.period_id,plan.expense_account_id,
        effect.created_by,effect.created_by,source.policy_version)
       OR expense.source_kind NOT IN ('extracted','clarified') THEN RETURN; END IF;

    RETURN QUERY SELECT effect.expense_id,effect.created_by,effect.created_at,
        expense.expense_created_at,plan.organisation_id,source.evidence_id,
        source.content_sha256,source.policy_version,expense.source_kind;
END;
$$;
REVOKE ALL ON FUNCTION omnixat_extraction.read_job_expense_summary(uuid,text,uuid,bytea,bytea) FROM PUBLIC;
