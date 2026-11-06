CREATE FUNCTION omnixat_extraction.read_csv_draft_amount(
    organisation uuid, evidence uuid, job uuid, requested_field text,
    requested_row integer, requested_column integer
)
RETURNS TABLE (amount text, source_kind text, created_by text, created_at timestamptz,
               policy_version text, content_sha256 bytea)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT d.amount, d.source_kind, d.created_by, d.created_at, r.policy_version, r.content_sha256
    FROM omnixat.evidence_draft_amounts d
    CROSS JOIN omnixat_extraction.read_csv_review(organisation, evidence, job) r
    WHERE d.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND d.job_id = job AND d.field_name = requested_field
      AND d.source_row = requested_row AND d.source_column = requested_column
      AND r.extractor_version = 'csv-amount-v1';
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_csv_draft_amount(uuid,uuid,uuid,text,integer,integer) FROM PUBLIC;
