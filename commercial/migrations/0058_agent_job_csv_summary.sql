-- Read-only, metadata-only recovery. No original bytes or monetary values leave
-- this function; all source, receipt, policy and answer reads share one snapshot.
CREATE FUNCTION omnixat_extraction.read_job_csv_summary(
    job uuid, worker text, lease uuid, expected_plan bytea
)
RETURNS TABLE (organisation_id uuid, evidence_id uuid, content_sha256 bytea,
    policy_version text, stored_at timestamptz, created_by text, created_at timestamptz, cells jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    source record;
    review record;
    selected_cells jsonb;
    item jsonb;
BEGIN
    SELECT t.organisation_id,t.evidence_id,t.content_sha256,p.selections,
           e.created_by,e.created_at INTO source
    FROM omnixat.agent_jobs j
    JOIN omnixat.agent_job_evidence_tasks t ON (t.tenant_id,t.job_id)=(j.tenant_id,j.id)
    JOIN omnixat.agent_job_csv_plans p ON (p.tenant_id,p.job_id)=(j.tenant_id,j.id)
    JOIN omnixat.agent_job_csv_effects e ON (e.tenant_id,e.job_id)=(j.tenant_id,j.id)
    WHERE j.tenant_id=tenant AND j.id=job AND j.status='running'
      AND j.claimed_by=worker AND j.lease_token=lease AND j.lease_until > statement_timestamp()
      AND p.plan_digest=expected_plan AND p.format_version=1;
    IF NOT FOUND THEN RETURN; END IF;

    SELECT * INTO review FROM omnixat_extraction.read_csv_review_with_answers(
        source.organisation_id,source.evidence_id,job);
    IF NOT FOUND OR review.extractor_version <> 'csv-amount-v1'
       OR review.content_sha256 IS DISTINCT FROM source.content_sha256 THEN RETURN; END IF;

    SELECT jsonb_agg(jsonb_build_object('field_name',a->'field_name','row',a->'row','column',a->'column') ORDER BY n)
    INTO selected_cells FROM jsonb_array_elements(review.amounts) WITH ORDINALITY AS x(a,n);
    IF selected_cells IS DISTINCT FROM source.selections THEN RETURN; END IF;

    -- Validate candidates before discarding values. Invalid stored candidates
    -- cannot acquire a plausible-looking metadata summary.
    FOR item IN SELECT value FROM jsonb_array_elements(review.amounts) LOOP
        IF jsonb_typeof(item) <> 'object' OR (SELECT count(*) FROM jsonb_object_keys(item)) <> 5
           OR NOT (item ?& ARRAY['field_name','row','column','status','amount'])
           OR jsonb_typeof(item->'status') <> 'string'
           OR item->>'status' NOT IN ('found','missing','blank','ambiguous') THEN RETURN; END IF;
        IF item->>'status' = 'found' THEN
            IF jsonb_typeof(item->'amount') <> 'string'
               OR NOT ((item->>'amount') COLLATE "C" ~ '^[+-]?[0-9]{1,18}(\.[0-9]{1,6})?$') THEN RETURN; END IF;
        ELSIF item->'amount' IS DISTINCT FROM 'null'::jsonb THEN RETURN;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(review.answers) answer
        WHERE NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(review.amounts) candidate
            WHERE (candidate->'field_name',candidate->'row',candidate->'column')=
                  (answer->'field_name',answer->'row',answer->'column')
              AND candidate->>'status' IN ('missing','blank','ambiguous')
        )
    ) THEN RETURN; END IF;

    RETURN QUERY SELECT source.organisation_id,source.evidence_id,source.content_sha256,
        review.policy_version,review.stored_at,source.created_by,source.created_at,
        (SELECT jsonb_agg(jsonb_build_object(
            'field_name',a->'field_name','row',a->'row','column',a->'column','status',a->'status',
            'answered',EXISTS (SELECT 1 FROM jsonb_array_elements(review.answers) b WHERE b->'field_name'=a->'field_name'),
            'unavailable',EXISTS (SELECT 1 FROM jsonb_array_elements(review.answers) b
                                 WHERE b->'field_name'=a->'field_name' AND b->'amount'='null'::jsonb)
        ) ORDER BY n) FROM jsonb_array_elements(review.amounts) WITH ORDINALITY AS x(a,n));
END;
$$;
REVOKE ALL ON FUNCTION omnixat_extraction.read_job_csv_summary(uuid,text,uuid,bytea) FROM PUBLIC;
