-- Keep the original review function available to the clarification writer.
CREATE FUNCTION omnixat_extraction.read_csv_review_with_answers(organisation uuid, evidence uuid, job uuid)
RETURNS TABLE (policy_version text, extractor_version text, content_sha256 bytea,
               amounts jsonb, stored_at timestamptz, answers jsonb)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT r.policy_version, r.extractor_version, r.content_sha256, r.amounts, r.stored_at,
           COALESCE((
               SELECT jsonb_agg(jsonb_build_object(
                   'field_name', a.field_name, 'row', a.source_row, 'column', a.source_column,
                   'amount', a.amount, 'answered_by', a.answered_by,
                   'answered_at', to_char(a.answered_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
               ) ORDER BY a.field_name COLLATE "C")
               FROM omnixat.csv_clarification_answers a
               WHERE a.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
                 AND a.job_id = job
           ), '[]'::jsonb)
    FROM omnixat_extraction.read_csv_review(organisation, evidence, job) r;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_csv_review_with_answers(uuid,uuid,uuid) FROM PUBLIC;
