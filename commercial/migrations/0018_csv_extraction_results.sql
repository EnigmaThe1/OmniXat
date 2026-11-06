CREATE TABLE omnixat.csv_extraction_results (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    content_sha256 bytea NOT NULL,
    byte_size integer NOT NULL,
    policy_version text NOT NULL,
    verdict text NOT NULL DEFAULT 'clean' CHECK (verdict = 'clean'),
    extractor_version text NOT NULL DEFAULT 'csv-amount-v1',
    amounts jsonb NOT NULL CHECK (
        CASE WHEN jsonb_typeof(amounts) = 'array'
             THEN jsonb_array_length(amounts) BETWEEN 1 AND 32 AND octet_length(amounts::text) <= 8192
             ELSE false END
    ),
    stored_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, evidence_id, content_sha256, byte_size)
        REFERENCES omnixat.evidence_quarantine(tenant_id, evidence_id, content_sha256, byte_size),
    FOREIGN KEY (tenant_id, evidence_id, policy_version, verdict)
        REFERENCES omnixat.evidence_scan_verdicts(tenant_id, evidence_id, policy_version, verdict)
);

ALTER TABLE omnixat.csv_extraction_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.csv_extraction_results FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.csv_extraction_results
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.csv_extraction_results FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.store_csv_result(
    organisation uuid, evidence uuid, job uuid, expected_policy text, expected_digest bytea, result_amounts jsonb
)
RETURNS TABLE (outcome text, stored_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    source_size integer;
    previous omnixat.csv_extraction_results%ROWTYPE;
BEGIN
    IF tenant IS NULL OR job IS NULL THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz;
        RETURN;
    END IF;

    -- Keep the admitted policy active until this transaction commits.
    PERFORM 1 FROM omnixat_extraction.active_scan_policy p
    WHERE p.policy_version = expected_policy FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz;
        RETURN;
    END IF;

    SELECT a.byte_size INTO source_size
    FROM omnixat_extraction.read_eligible_original(organisation, evidence) a
    WHERE a.policy_version = expected_policy AND a.content_sha256 = expected_digest
      AND a.media_type = 'text/csv' AND a.byte_size <= 524288;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.csv_extraction_results
        (tenant_id, job_id, evidence_id, content_sha256, byte_size, policy_version, amounts)
    VALUES (tenant, job, evidence, expected_digest, source_size, expected_policy, result_amounts)
    ON CONFLICT (tenant_id, job_id) DO NOTHING;

    SELECT * INTO STRICT previous FROM omnixat.csv_extraction_results r
    WHERE r.tenant_id = tenant AND r.job_id = job;
    IF previous.evidence_id <> evidence OR previous.content_sha256 <> expected_digest
       OR previous.policy_version <> expected_policy OR previous.amounts <> result_amounts
       OR previous.extractor_version <> 'csv-amount-v1' THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.stored_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb) FROM PUBLIC;
