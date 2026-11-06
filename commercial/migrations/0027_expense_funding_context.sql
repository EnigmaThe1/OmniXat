-- Internal payer references are opaque identifiers, not bank details or identity assertions.
CREATE TABLE omnixat.expense_funding_sources (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
    payer_id uuid NOT NULL CHECK (payer_id <> '00000000-0000-0000-0000-000000000000'),
    funding_kind text NOT NULL CHECK (funding_kind IN ('business_funds', 'personal_funds')),
    eligible_for_drafts boolean NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, organisation_id, id),
    UNIQUE (tenant_id, organisation_id, id, payer_id, funding_kind),
    FOREIGN KEY (tenant_id, organisation_id) REFERENCES omnixat.organisations(tenant_id, id)
);

ALTER TABLE omnixat.csv_expense_drafts ADD UNIQUE (tenant_id, organisation_id, id);

CREATE TABLE omnixat.expense_funding_context (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    draft_id uuid NOT NULL,
    funding_source_id uuid NOT NULL,
    payer_id uuid NOT NULL,
    funding_kind text NOT NULL,
    recorded_by text NOT NULL CHECK (length(btrim(recorded_by)) BETWEEN 1 AND 200),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, draft_id),
    FOREIGN KEY (tenant_id, organisation_id, draft_id)
        REFERENCES omnixat.csv_expense_drafts(tenant_id, organisation_id, id),
    FOREIGN KEY (tenant_id, organisation_id, funding_source_id, payer_id, funding_kind)
        REFERENCES omnixat.expense_funding_sources(tenant_id, organisation_id, id, payer_id, funding_kind)
);

ALTER TABLE omnixat.expense_funding_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_funding_sources FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_funding_sources
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);

ALTER TABLE omnixat.expense_funding_context ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_funding_context FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_funding_context
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);

REVOKE ALL ON omnixat.expense_funding_sources, omnixat.expense_funding_context FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.record_expense_funding_context(
    organisation uuid, requested_draft uuid, requested_source uuid, requested_payer uuid, actor_id text
)
RETURNS TABLE (outcome text, funding_kind text, recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    selected_kind text;
    previous omnixat.expense_funding_context%ROWTYPE;
BEGIN
    SELECT s.funding_kind INTO selected_kind FROM omnixat.expense_funding_sources s
    WHERE s.tenant_id = tenant AND s.organisation_id = organisation AND s.id = requested_source
      AND s.payer_id = requested_payer AND s.eligible_for_drafts
    FOR SHARE OF s;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;

    PERFORM 1 FROM omnixat_extraction.read_csv_expense_draft(organisation, requested_draft);
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_funding_context
        (tenant_id, organisation_id, draft_id, funding_source_id, payer_id, funding_kind, recorded_by)
    VALUES (tenant, organisation, requested_draft, requested_source, requested_payer, selected_kind, actor_id)
    ON CONFLICT (tenant_id, draft_id) DO NOTHING;

    SELECT c.* INTO STRICT previous FROM omnixat.expense_funding_context c
    WHERE c.tenant_id = tenant AND c.draft_id = requested_draft;
    IF (previous.organisation_id, previous.funding_source_id, previous.payer_id,
        previous.funding_kind, previous.recorded_by)
       IS DISTINCT FROM (organisation, requested_source, requested_payer, selected_kind, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.funding_kind, previous.recorded_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.record_expense_funding_context(uuid,uuid,uuid,uuid,text) FROM PUBLIC;
