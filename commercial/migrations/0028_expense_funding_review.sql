CREATE FUNCTION omnixat_extraction.read_expense_funding_context(organisation uuid, requested_draft uuid)
RETURNS TABLE (
    funding_source_id uuid, payer_id uuid, funding_kind text,
    recorded_by text, recorded_at timestamptz, source_eligible boolean
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT c.funding_source_id, c.payer_id, c.funding_kind, c.recorded_by,
           c.recorded_at, COALESCE(s.eligible_for_drafts, false)
    FROM omnixat_extraction.read_csv_expense_draft(organisation, requested_draft) d
    LEFT JOIN omnixat.expense_funding_context c
      ON c.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
     AND c.organisation_id = organisation AND c.draft_id = d.draft_id
    LEFT JOIN omnixat.expense_funding_sources s
      ON (s.tenant_id, s.organisation_id, s.id, s.payer_id, s.funding_kind) =
         (c.tenant_id, c.organisation_id, c.funding_source_id, c.payer_id, c.funding_kind);
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_expense_funding_context(uuid,uuid) FROM PUBLIC;
