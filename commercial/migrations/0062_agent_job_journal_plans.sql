-- Proposed intent only; actual funding context and journals remain separate.
ALTER TABLE omnixat.agent_job_expense_effects ADD UNIQUE (tenant_id, job_id, expense_id);
CREATE TABLE omnixat.agent_job_journal_plans (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    expense_id uuid NOT NULL,
    format_version integer NOT NULL DEFAULT 1 CHECK (format_version = 1),
    funding_source_id uuid NOT NULL,
    payer_id uuid NOT NULL,
    funding_kind text NOT NULL CHECK (funding_kind IN ('business_funds','personal_funds')),
    counterpart_account_id uuid NOT NULL,
    csv_plan_digest bytea NOT NULL CHECK (octet_length(csv_plan_digest) = 32),
    expense_plan_digest bytea NOT NULL CHECK (octet_length(expense_plan_digest) = 32),
    plan_digest bytea NOT NULL CHECK (octet_length(plan_digest) = 32),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id, expense_id)
        REFERENCES omnixat.agent_job_expense_effects(tenant_id, job_id, expense_id),
    FOREIGN KEY (tenant_id, job_id, organisation_id)
        REFERENCES omnixat.agent_job_evidence_tasks(tenant_id, job_id, organisation_id),
    FOREIGN KEY (tenant_id, organisation_id, funding_source_id, payer_id, funding_kind)
        REFERENCES omnixat.expense_funding_sources(tenant_id, organisation_id, id, payer_id, funding_kind),
    FOREIGN KEY (tenant_id, organisation_id, funding_source_id, counterpart_account_id)
        REFERENCES omnixat.expense_counterpart_policy(tenant_id, organisation_id, funding_source_id, account_id)
);
ALTER TABLE omnixat.agent_job_journal_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_journal_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_journal_plans
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_journal_plans FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.save_job_journal_plan(
    job uuid, worker text, lease uuid, expected_csv bytea, expected_expense bytea,
    requested_source uuid, requested_payer uuid, requested_kind text,
    requested_counterpart uuid, requested_digest bytea
)
RETURNS TABLE (expense_id uuid, format_version integer, funding_source_id uuid, payer_id uuid,
    funding_kind text, counterpart_account_id uuid, plan_digest bytea, created_by text, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    expense record;
    previous omnixat.agent_job_journal_plans%ROWTYPE;
BEGIN
    PERFORM 1 FROM omnixat.agent_jobs j WHERE j.tenant_id=tenant AND j.id=job FOR UPDATE;
    PERFORM 1 FROM omnixat.agent_jobs j WHERE j.tenant_id=tenant AND j.id=job
        AND j.status='running' AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > clock_timestamp();
    IF NOT FOUND THEN RAISE EXCEPTION 'Live worker claim unavailable' USING ERRCODE='22023'; END IF;

    SELECT * INTO expense FROM omnixat_extraction.read_job_expense_summary(job,worker,lease,expected_csv,expected_expense);
    IF NOT FOUND THEN RAISE EXCEPTION 'Job expense unavailable' USING ERRCODE='22023'; END IF;
    PERFORM 1 FROM omnixat.expense_funding_sources s
        JOIN omnixat.expense_counterpart_policy c ON c.tenant_id=s.tenant_id
            AND c.organisation_id=s.organisation_id AND c.funding_source_id=s.id
        JOIN omnixat.agent_job_expense_plans p ON p.tenant_id=s.tenant_id AND p.organisation_id=s.organisation_id
        WHERE s.tenant_id=tenant AND s.organisation_id=expense.organisation_id AND p.job_id=job
            AND s.id=requested_source AND s.payer_id=requested_payer AND s.funding_kind=requested_kind
            AND s.eligible_for_drafts AND c.eligible_for_drafts AND c.account_id=requested_counterpart
            AND c.account_id <> p.expense_account_id
        FOR SHARE OF s,c;
    IF NOT FOUND THEN RAISE EXCEPTION 'Funding or counterpart mapping unavailable' USING ERRCODE='22023'; END IF;

    INSERT INTO omnixat.agent_job_journal_plans
        (tenant_id,job_id,organisation_id,expense_id,funding_source_id,payer_id,funding_kind,
         counterpart_account_id,csv_plan_digest,expense_plan_digest,plan_digest,created_by)
        VALUES (tenant,job,expense.organisation_id,expense.expense_id,requested_source,requested_payer,requested_kind,
            requested_counterpart,expected_csv,expected_expense,requested_digest,worker)
        ON CONFLICT (tenant_id,job_id) DO NOTHING;
    SELECT p.* INTO STRICT previous FROM omnixat.agent_job_journal_plans p WHERE p.tenant_id=tenant AND p.job_id=job;
    IF (previous.expense_id,previous.funding_source_id,previous.payer_id,previous.funding_kind,
        previous.counterpart_account_id,previous.csv_plan_digest,previous.expense_plan_digest,previous.plan_digest)
       IS DISTINCT FROM (expense.expense_id,requested_source,requested_payer,requested_kind,
        requested_counterpart,expected_csv,expected_expense,requested_digest) THEN
        RAISE EXCEPTION 'Job journal intent conflicts' USING ERRCODE='23505';
    END IF;
    PERFORM 1 FROM omnixat.agent_jobs j WHERE j.tenant_id=tenant AND j.id=job
        AND j.status='running' AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > clock_timestamp();
    IF NOT FOUND THEN RAISE EXCEPTION 'Live worker claim unavailable' USING ERRCODE='22023'; END IF;
    RETURN QUERY SELECT previous.expense_id,previous.format_version,previous.funding_source_id,previous.payer_id,
        previous.funding_kind,previous.counterpart_account_id,previous.plan_digest,previous.created_by,previous.created_at;
END;
$$;
REVOKE ALL ON FUNCTION omnixat_extraction.save_job_journal_plan(uuid,text,uuid,bytea,bytea,uuid,uuid,text,uuid,bytea) FROM PUBLIC;
