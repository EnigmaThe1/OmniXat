CREATE TABLE omnixat.csv_clarification_answers (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    field_name text NOT NULL CHECK (field_name COLLATE "C" ~ '^[a-z][a-z0-9_]{0,63}$'),
    source_row integer NOT NULL CHECK (source_row BETWEEN 1 AND 5000),
    source_column integer NOT NULL CHECK (source_column BETWEEN 1 AND 64),
    amount text CHECK (amount COLLATE "C" ~ '^[+-]?[0-9]{1,18}(\.[0-9]{1,6})?$'),
    answered_by text NOT NULL CHECK (char_length(answered_by) BETWEEN 1 AND 200 AND btrim(answered_by) <> ''),
    answered_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, job_id, field_name),
    FOREIGN KEY (tenant_id, job_id) REFERENCES omnixat.csv_extraction_results(tenant_id, job_id)
);

ALTER TABLE omnixat.csv_clarification_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.csv_clarification_answers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.csv_clarification_answers
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.csv_clarification_answers FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.store_csv_answer(
    organisation uuid, evidence uuid, job uuid, answer_field text,
    answer_row integer, answer_column integer, answer_amount text, actor_id text
)
RETURNS TABLE (outcome text, stored_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    matching_cells integer;
    previous omnixat.csv_clarification_answers%ROWTYPE;
BEGIN
    -- Serialize with policy rotation until the answer transaction commits.
    PERFORM 1 FROM omnixat_extraction.active_scan_policy p
    JOIN omnixat.csv_extraction_results r ON r.policy_version = p.policy_version
    WHERE r.tenant_id = tenant AND r.job_id = job AND r.evidence_id = evidence
    FOR SHARE OF p;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz;
        RETURN;
    END IF;

    SELECT count(*) INTO matching_cells
    FROM omnixat_extraction.read_csv_review(organisation, evidence, job) r
    CROSS JOIN LATERAL jsonb_array_elements(r.amounts) AS item(cell)
    WHERE r.extractor_version = 'csv-amount-v1'
      AND cell->>'field_name' = answer_field
      AND cell->'row' = to_jsonb(answer_row) AND cell->'column' = to_jsonb(answer_column)
      AND cell->>'status' IN ('missing', 'blank', 'ambiguous')
      AND cell->'amount' = 'null'::jsonb;
    IF matching_cells <> 1 THEN
        RETURN QUERY SELECT 'ineligible'::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.csv_clarification_answers
        (tenant_id, job_id, field_name, source_row, source_column, amount, answered_by)
    VALUES (tenant, job, answer_field, answer_row, answer_column, answer_amount, actor_id)
    ON CONFLICT (tenant_id, job_id, field_name) DO NOTHING;

    SELECT * INTO STRICT previous FROM omnixat.csv_clarification_answers a
    WHERE a.tenant_id = tenant AND a.job_id = job AND a.field_name = answer_field;
    IF previous.source_row <> answer_row OR previous.source_column <> answer_column
       OR previous.amount IS DISTINCT FROM answer_amount OR previous.answered_by <> actor_id THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.answered_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.store_csv_answer(uuid,uuid,uuid,text,integer,integer,text,text) FROM PUBLIC;
