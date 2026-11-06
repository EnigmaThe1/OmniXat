CREATE TABLE omnixat.evidence_draft_amounts (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    field_name text NOT NULL CHECK (field_name COLLATE "C" ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_row integer NOT NULL CHECK (source_row BETWEEN 1 AND 5000),
    source_column integer NOT NULL CHECK (source_column BETWEEN 1 AND 64),
    source_kind text NOT NULL CHECK (source_kind IN ('extracted', 'clarified')),
    amount text NOT NULL CHECK (amount COLLATE "C" ~ '^[+-]?[0-9]{1,18}(\.[0-9]{1,6})?$'),
    created_by text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 200 AND btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, job_id, field_name),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.csv_extraction_results(tenant_id, job_id)
);

ALTER TABLE omnixat.evidence_draft_amounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_draft_amounts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_draft_amounts
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.evidence_draft_amounts FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.create_csv_draft_amount(
    organisation uuid, evidence uuid, job uuid, requested_field text,
    requested_row integer, requested_column integer, actor_id text
)
RETURNS TABLE (outcome text, stored_at timestamptz, stored_source text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    selected_cell jsonb;
    field_count bigint;
    source_amount text;
    source_type text;
    previous omnixat.evidence_draft_amounts%ROWTYPE;
BEGIN
    PERFORM 1 FROM omnixat_extraction.active_scan_policy p
    JOIN omnixat.csv_extraction_results r ON r.policy_version = p.policy_version
    WHERE r.tenant_id = tenant AND r.job_id = job AND r.evidence_id = evidence
    FOR SHARE OF p;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz, NULL::text;
        RETURN;
    END IF;

    SELECT cell, count(*) OVER () INTO selected_cell, field_count
    FROM omnixat_extraction.read_csv_review(organisation, evidence, job) r
    CROSS JOIN LATERAL jsonb_array_elements(r.amounts) AS item(cell)
    WHERE r.extractor_version = 'csv-amount-v1' AND cell->>'field_name' = requested_field;

    IF field_count IS DISTINCT FROM 1::bigint
       OR selected_cell->'row' IS DISTINCT FROM to_jsonb(requested_row)
       OR selected_cell->'column' IS DISTINCT FROM to_jsonb(requested_column) THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz, NULL::text;
        RETURN;
    END IF;

    IF selected_cell->>'status' = 'found' AND jsonb_typeof(selected_cell->'amount') = 'string' THEN
        source_type := 'extracted';
        source_amount := selected_cell->>'amount';
    ELSIF selected_cell->>'status' IN ('missing', 'blank', 'ambiguous')
          AND selected_cell->'amount' = 'null'::jsonb THEN
        source_type := 'clarified';
        SELECT a.amount INTO source_amount FROM omnixat.csv_clarification_answers a
        WHERE a.tenant_id = tenant AND a.job_id = job AND a.field_name = requested_field
          AND a.source_row = requested_row AND a.source_column = requested_column;
    END IF;
    IF source_amount IS NULL OR source_amount COLLATE "C" !~ '^[+-]?[0-9]{1,18}(\.[0-9]{1,6})?$' THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz, NULL::text;
        RETURN;
    END IF;

    INSERT INTO omnixat.evidence_draft_amounts
        (tenant_id, job_id, field_name, source_row, source_column, source_kind, amount, created_by)
    VALUES (tenant, job, requested_field, requested_row, requested_column, source_type, source_amount, actor_id)
    ON CONFLICT (tenant_id, job_id, field_name) DO NOTHING;

    SELECT * INTO STRICT previous FROM omnixat.evidence_draft_amounts d
    WHERE d.tenant_id = tenant AND d.job_id = job AND d.field_name = requested_field;
    IF (previous.source_row, previous.source_column, previous.source_kind, previous.amount, previous.created_by)
       IS DISTINCT FROM (requested_row, requested_column, source_type, source_amount, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz, NULL::text;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.created_at, previous.source_kind;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.create_csv_draft_amount(uuid,uuid,uuid,text,integer,integer,text) FROM PUBLIC;
