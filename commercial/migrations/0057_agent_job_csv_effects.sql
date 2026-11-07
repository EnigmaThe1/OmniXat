CREATE TABLE omnixat.agent_job_csv_effects (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.agent_job_csv_plans(tenant_id, job_id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.csv_extraction_results(tenant_id, job_id)
);
ALTER TABLE omnixat.agent_job_csv_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.agent_job_csv_effects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.agent_job_csv_effects
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.agent_job_csv_effects FROM PUBLIC;

-- Dedicated execute-only worker role. Caller establishes signed current authority;
-- this boundary serializes job state and stores only the pinned plan's result.
CREATE FUNCTION omnixat_extraction.store_job_csv_result(
    job uuid, worker text, lease uuid, expected_evidence uuid, expected_plan bytea,
    expected_policy text, expected_digest bytea, result_amounts jsonb
)
RETURNS TABLE (stored_at timestamptz, created_by text, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    task omnixat.agent_job_evidence_tasks%ROWTYPE;
    plan omnixat.agent_job_csv_plans%ROWTYPE;
    result_record record;
    selected_cells jsonb;
BEGIN
    PERFORM 1 FROM omnixat.agent_jobs j
    WHERE j.tenant_id=tenant AND j.id=job FOR UPDATE;
    PERFORM 1 FROM omnixat.agent_jobs j
    WHERE j.tenant_id=tenant AND j.id=job AND j.status='running'
      AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Claim expired, superseded or job unavailable' USING ERRCODE='22023';
    END IF;
    SELECT * INTO task FROM omnixat.agent_job_evidence_tasks t WHERE t.tenant_id=tenant AND t.job_id=job;
    SELECT * INTO plan FROM omnixat.agent_job_csv_plans p WHERE p.tenant_id=tenant AND p.job_id=job;
    IF plan.job_id IS NULL OR task.job_id IS NULL OR plan.plan_digest IS DISTINCT FROM expected_plan
       OR task.content_sha256 IS DISTINCT FROM expected_digest
       OR task.evidence_id IS DISTINCT FROM expected_evidence THEN
        RAISE EXCEPTION 'Pinned extraction inputs changed or unavailable' USING ERRCODE='22023';
    END IF;
    SELECT jsonb_agg(jsonb_build_object('field_name', a->'field_name', 'row', a->'row', 'column', a->'column') ORDER BY n)
    INTO selected_cells FROM jsonb_array_elements(result_amounts) WITH ORDINALITY AS x(a,n);
    IF selected_cells IS DISTINCT FROM plan.selections THEN
        RAISE EXCEPTION 'Result does not match saved plan' USING ERRCODE='22023';
    END IF;
    SELECT * INTO result_record FROM omnixat_extraction.store_csv_result(
        task.organisation_id, task.evidence_id, job, expected_policy, expected_digest, result_amounts);
    IF result_record.outcome <> 'stored' THEN
        RAISE EXCEPTION 'Extraction result unavailable: %', result_record.outcome USING ERRCODE='22023';
    END IF;
    INSERT INTO omnixat.agent_job_csv_effects (tenant_id,job_id,created_by)
    VALUES (tenant,job,worker) ON CONFLICT (tenant_id,job_id) DO NOTHING;
    -- A slow extraction write must roll back even if its lease expired after admission.
    PERFORM 1 FROM omnixat.agent_jobs j
    WHERE j.tenant_id=tenant AND j.id=job AND j.status='running'
      AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Claim expired during extraction' USING ERRCODE='22023';
    END IF;
    RETURN QUERY SELECT result_record.stored_at, e.created_by, e.created_at
        FROM omnixat.agent_job_csv_effects e WHERE e.tenant_id=tenant AND e.job_id=job;
END;
$$;
REVOKE ALL ON FUNCTION omnixat_extraction.store_job_csv_result(uuid,text,uuid,uuid,bytea,text,bytea,jsonb) FROM PUBLIC;
