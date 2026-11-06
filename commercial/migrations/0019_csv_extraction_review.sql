CREATE FUNCTION omnixat_extraction.read_csv_review(organisation uuid, evidence uuid, job uuid)
RETURNS TABLE (policy_version text, extractor_version text, content_sha256 bytea,
               amounts jsonb, stored_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT r.policy_version, r.extractor_version, r.content_sha256, r.amounts, r.stored_at
    FROM omnixat.csv_extraction_results r
    WHERE r.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND r.evidence_id = evidence AND r.job_id = job
      AND EXISTS (
          SELECT 1 FROM omnixat_extraction.read_eligible_original(organisation, evidence) a
          WHERE (a.policy_version, a.content_sha256, a.byte_size) =
                (r.policy_version, r.content_sha256, r.byte_size)
            AND a.media_type = 'text/csv'
      );
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_csv_review(uuid,uuid,uuid) FROM PUBLIC;
