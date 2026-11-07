CREATE FUNCTION omnixat_extraction.read_expense_journal_amount_correction(
    organisation uuid, requested_journal uuid, expected_snapshot bytea, requested_job uuid,
    requested_field text, requested_row integer, requested_column integer
)
RETURNS TABLE (
    evidence_id uuid, content_sha256 bytea, policy_version text, amount text,
    previous_pence numeric, expense_account_id uuid, counterpart_account_id uuid
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT l.evidence_id, r.content_sha256, r.policy_version, selection.cell->>'amount',
           j.amount_pence, j.expense_account_id, j.counterpart_account_id
    FROM omnixat_extraction.read_expense_journal_review(organisation, requested_journal) j
    JOIN omnixat.expense_journal_clarification_evidence l
      ON l.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND l.organisation_id = organisation AND l.journal_id = j.journal_id
     AND l.snapshot_sha256 = j.snapshot_sha256 AND l.reason = 'amount'
    CROSS JOIN LATERAL omnixat_extraction.read_csv_review(organisation, l.evidence_id, requested_job) r
    CROSS JOIN LATERAL (
        SELECT cell, count(*) OVER () AS field_count
        FROM jsonb_array_elements(r.amounts) AS item(cell)
        WHERE cell->>'field_name' = requested_field
    ) selection
    WHERE j.snapshot_sha256 = expected_snapshot
      AND r.content_sha256 = l.content_sha256 AND r.extractor_version = 'csv-amount-v1'
      AND selection.field_count = 1
      AND selection.cell->'row' = to_jsonb(requested_row)
      AND selection.cell->'column' = to_jsonb(requested_column)
      AND selection.cell->>'status' = 'found'
      AND jsonb_typeof(selection.cell->'amount') = 'string'
      AND (selection.cell->>'amount') COLLATE "C" ~ '^[+-]?[0-9]{1,18}(\.[0-9]{1,6})?$';
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_journal_amount_correction(uuid,uuid,bytea,uuid,text,integer,integer)
    FROM PUBLIC;
