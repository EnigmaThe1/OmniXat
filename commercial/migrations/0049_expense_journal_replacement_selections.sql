ALTER TABLE omnixat.expense_journal_replacements
    ADD UNIQUE (tenant_id, organisation_id, original_journal_id, id);

CREATE TABLE omnixat.expense_journal_replacement_selections (
    tenant_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    original_journal_id uuid NOT NULL,
    replacement_id uuid NOT NULL,
    original_snapshot_sha256 bytea NOT NULL CHECK (octet_length(original_snapshot_sha256) = 32),
    proposal_sha256 bytea NOT NULL CHECK (octet_length(proposal_sha256) = 32),
    selected_by text NOT NULL CHECK (char_length(selected_by) BETWEEN 1 AND 200 AND btrim(selected_by) <> ''),
    selected_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, original_journal_id),
    FOREIGN KEY (tenant_id, organisation_id, original_journal_id, replacement_id)
        REFERENCES omnixat.expense_journal_replacements (tenant_id, organisation_id, original_journal_id, id)
);

ALTER TABLE omnixat.expense_journal_replacement_selections ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.expense_journal_replacement_selections FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.expense_journal_replacement_selections
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid);
REVOKE ALL ON omnixat.expense_journal_replacement_selections FROM PUBLIC;

CREATE FUNCTION omnixat_extraction.select_expense_journal_replacement(
    organisation uuid, requested_journal uuid, requested_replacement uuid, expected_proposal bytea, actor_id text
)
RETURNS TABLE (outcome text, original_journal uuid, replacement_id uuid,
               snapshot_sha256 bytea, proposal_sha256 bytea, selected_by text, selected_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$
DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid;
    saved omnixat.expense_journal_replacements%ROWTYPE;
    checked record;
    candidate record;
    previous omnixat.expense_journal_replacement_selections%ROWTYPE;
BEGIN
    SELECT r.* INTO saved FROM omnixat.expense_journal_replacements r
    WHERE r.tenant_id = tenant AND r.organisation_id = organisation
      AND r.original_journal_id = requested_journal AND r.id = requested_replacement
      AND r.proposal_sha256 = expected_proposal;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::bytea, NULL::bytea, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;

    -- Replay the existing draft's original inputs to hold its source, journal,
    -- policy and selected review locks through this selection's commit.
    SELECT * INTO checked FROM omnixat_extraction.create_expense_journal_replacement(
        organisation, saved.proposal_id, saved.proposal_sha256, saved.reviewer_id, saved.created_by
    );
    IF checked.outcome <> 'stored' OR checked.replacement_id IS DISTINCT FROM requested_replacement THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::bytea, NULL::bytea, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;

    -- Lock after the existing writer's locks to preserve its acquisition order.
    PERFORM 1 FROM omnixat.expense_journal_replacements r
    WHERE r.tenant_id = tenant AND r.id = requested_replacement FOR SHARE;
    SELECT * INTO candidate FROM omnixat_extraction.read_saved_expense_journal_replacement(
        organisation, requested_replacement
    );
    IF NOT FOUND OR candidate.journal_id IS DISTINCT FROM requested_journal
       OR candidate.proposal_sha256 IS DISTINCT FROM expected_proposal THEN
        RETURN QUERY SELECT 'unavailable'::text, NULL::uuid, NULL::uuid, NULL::bytea, NULL::bytea, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;

    INSERT INTO omnixat.expense_journal_replacement_selections (
        tenant_id, organisation_id, original_journal_id, replacement_id,
        original_snapshot_sha256, proposal_sha256, selected_by
    ) VALUES (
        tenant, organisation, requested_journal, requested_replacement,
        candidate.snapshot_sha256, expected_proposal, actor_id
    ) ON CONFLICT DO NOTHING;

    SELECT s.* INTO STRICT previous FROM omnixat.expense_journal_replacement_selections s
    WHERE s.tenant_id = tenant AND s.original_journal_id = requested_journal;
    IF (previous.organisation_id, previous.replacement_id, previous.original_snapshot_sha256,
        previous.proposal_sha256, previous.selected_by)
       IS DISTINCT FROM (organisation, requested_replacement, candidate.snapshot_sha256, expected_proposal, actor_id) THEN
        RETURN QUERY SELECT 'conflict'::text, NULL::uuid, NULL::uuid, NULL::bytea, NULL::bytea, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'stored'::text, previous.original_journal_id, previous.replacement_id,
        previous.original_snapshot_sha256, previous.proposal_sha256, previous.selected_by, previous.selected_at;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.select_expense_journal_replacement(uuid,uuid,uuid,bytea,text) FROM PUBLIC;
