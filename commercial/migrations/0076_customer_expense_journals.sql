-- Customer preparation only: no posting, review decision or submission capability.
CREATE SCHEMA omnixat_customer_journals;
REVOKE ALL ON SCHEMA omnixat_customer_journals FROM PUBLIC;

CREATE FUNCTION omnixat_customer_journals._preview(organisation uuid, evidence uuid, requested_draft uuid, requested_account uuid)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on
AS $$
    SELECT to_jsonb(p) || jsonb_build_object('preview_sha256',encode(sha256(convert_to(
        jsonb_build_array('customer-expense-journal-preview-v1',current_setting('omnixat.tenant_id'),
            organisation,requested_draft,to_jsonb(p))::text,'UTF8')),'hex'))
    FROM omnixat_extraction.read_expense_journal_preview(organisation,requested_draft,requested_account) p
    WHERE p.evidence_id=evidence
$$;
REVOKE ALL ON FUNCTION omnixat_customer_journals._preview(uuid,uuid,uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_customer_journals.inspect(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    member_role text; saved_id uuid; saved jsonb; choices jsonb := '[]'::jsonb;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT m.role INTO member_role FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
    WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
      AND i.actor_kind='human' AND issued_at>i.tokens_valid_after AND m.tenant_id=tenant AND m.revoked_at IS NULL;
    IF member_role IS NULL THEN RAISE insufficient_privilege; END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.csv_expense_drafts d WHERE d.tenant_id=tenant
        AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft)
       OR NOT EXISTS (SELECT 1 FROM omnixat_extraction.read_expense_funding_context(organisation,requested_draft))
    THEN RETURN NULL; END IF;
    SELECT j.id INTO saved_id FROM omnixat.expense_journal_drafts j
      WHERE j.tenant_id=tenant AND j.organisation_id=organisation AND j.expense_draft_id=requested_draft;
    IF saved_id IS NOT NULL THEN
        SELECT to_jsonb(j) INTO saved FROM omnixat_extraction.read_expense_journal_review(organisation,saved_id) j;
    ELSIF member_role IN ('owner','editor') THEN
        SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY c.account_id),'[]'::jsonb) INTO choices FROM (
          SELECT p.account_id FROM omnixat.expense_counterpart_policy p
          JOIN omnixat.expense_funding_context f ON (f.tenant_id,f.organisation_id,f.funding_source_id)=
            (p.tenant_id,p.organisation_id,p.funding_source_id)
          WHERE p.tenant_id=tenant AND p.organisation_id=organisation AND f.draft_id=requested_draft
            AND p.eligible_for_drafts AND omnixat_customer_journals._preview(organisation,evidence,requested_draft,p.account_id) IS NOT NULL
          ORDER BY p.account_id LIMIT 21) c;
    END IF;
    RETURN jsonb_build_object('journal',saved,'saved_unavailable',saved_id IS NOT NULL AND saved IS NULL,'choices',choices);
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_journals.inspect(text,text,bigint,uuid,uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_customer_journals.preview(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_actor uuid, requested_account uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid; actor uuid;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
    WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
      AND i.actor_kind='human' AND issued_at>i.tokens_valid_after AND m.tenant_id=tenant
      AND m.revoked_at IS NULL AND m.role IN ('owner','editor');
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    RETURN omnixat_customer_journals._preview(organisation,evidence,requested_draft,requested_account);
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_journals.preview(text,text,bigint,uuid,uuid,uuid,uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_customer_journals.create_draft(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_actor uuid,
    requested_account uuid, expected_preview bytea
) RETURNS TABLE (journal_id uuid,created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on SET lock_timeout = '1s'
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid; actor uuid; result record; candidate jsonb;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
    WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
      AND i.actor_kind='human' AND issued_at>i.tokens_valid_after AND m.tenant_id=tenant
      AND m.revoked_at IS NULL AND m.role IN ('owner','editor') FOR SHARE OF i,m;
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    IF expected_preview IS NULL OR octet_length(expected_preview)<>32 OR requested_account IS NULL
        OR requested_account='00000000-0000-0000-0000-000000000000'::uuid THEN RAISE invalid_parameter_value; END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.csv_expense_drafts d WHERE d.tenant_id=tenant
        AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft)
    THEN RAISE check_violation; END IF;
    -- The shared writer locks current identity-independent policy, funding, source,
    -- quarantine and accounting gates. Any subsequent digest failure rolls back its insert.
    SELECT * INTO result FROM omnixat_extraction.create_expense_journal_draft(organisation,requested_draft,requested_account,actor::text);
    IF result.outcome='conflict' THEN RAISE unique_violation; END IF;
    IF result.outcome IS DISTINCT FROM 'stored' THEN RAISE check_violation; END IF;
    candidate := omnixat_customer_journals._preview(organisation,evidence,requested_draft,requested_account);
    IF candidate IS NULL THEN RAISE check_violation; END IF;
    IF decode(candidate->>'preview_sha256','hex')<>expected_preview THEN RAISE serialization_failure; END IF;
    RETURN QUERY SELECT result.journal_id,result.created_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_journals.create_draft(text,text,bigint,uuid,uuid,uuid,uuid,uuid,bytea) FROM PUBLIC;
