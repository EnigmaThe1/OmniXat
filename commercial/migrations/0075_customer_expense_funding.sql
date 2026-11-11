CREATE SCHEMA omnixat_customer_funding;
REVOKE ALL ON SCHEMA omnixat_customer_funding FROM PUBLIC;

CREATE FUNCTION omnixat_customer_funding.read_funding(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    member_role text; saved record; choices jsonb;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT m.role INTO member_role FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
        AND m.tenant_id=tenant AND m.revoked_at IS NULL;
    IF member_role IS NULL THEN RAISE insufficient_privilege; END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.csv_expense_drafts d
        WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft) THEN
        RETURN NULL;
    END IF;
    SELECT * INTO saved FROM omnixat_extraction.read_expense_funding_context(organisation,requested_draft);
    IF NOT FOUND THEN RETURN NULL; END IF;
    choices := '[]'::jsonb;
    IF member_role IN ('owner','editor') THEN
        SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.id),'[]'::jsonb) INTO choices FROM (
            SELECT id,payer_id,funding_kind FROM omnixat.expense_funding_sources
            WHERE tenant_id=tenant AND organisation_id=organisation AND eligible_for_drafts
            ORDER BY id LIMIT 21) s;
    END IF;
    RETURN jsonb_build_object('funding',CASE WHEN saved.funding_source_id IS NULL THEN NULL ELSE to_jsonb(saved) END,
                             'choices',choices);
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_funding.read_funding(text,text,bigint,uuid,uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_customer_funding.record_funding(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_actor uuid,
    requested_source uuid, requested_payer uuid
) RETURNS TABLE (funding_kind text,recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    actor uuid; saved omnixat.csv_expense_drafts%ROWTYPE; result record;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
        AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor')
      FOR SHARE OF i,m;
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    IF requested_source IS NULL OR requested_payer IS NULL
       OR requested_source='00000000-0000-0000-0000-000000000000'::uuid
       OR requested_payer='00000000-0000-0000-0000-000000000000'::uuid THEN RAISE invalid_parameter_value; END IF;
    SELECT d.* INTO saved FROM omnixat.csv_expense_drafts d
      WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft
      FOR SHARE OF d;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    -- Preserve the same current-policy/context/observation gates used by expense
    -- creation until funding storage commits. No assumption is made from an old read.
    PERFORM 1 FROM omnixat_extraction.active_scan_policy FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    PERFORM 1 FROM omnixat.expense_accounting_periods p JOIN omnixat.expense_account_policy a USING(tenant_id,organisation_id)
      WHERE p.tenant_id=tenant AND p.organisation_id=organisation AND p.id=saved.period_id AND p.open_for_drafts
        AND saved.accounting_date BETWEEN p.starts_on AND p.ends_on
        AND a.account_id=saved.expense_account_id AND a.eligible_for_drafts FOR SHARE OF p,a;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    PERFORM 1 FROM omnixat.evidence_quarantine q WHERE q.tenant_id=tenant AND q.evidence_id=evidence FOR UPDATE OF q;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    PERFORM 1 FROM omnixat.evidence_scan_claims c WHERE c.tenant_id=tenant AND c.evidence_id=evidence FOR SHARE NOWAIT;
    SELECT * INTO result FROM omnixat_extraction.record_expense_funding_context(
        organisation,requested_draft,requested_source,requested_payer,actor::text);
    IF result.outcome='conflict' THEN RAISE unique_violation; END IF;
    IF result.outcome IS DISTINCT FROM 'stored' THEN RAISE check_violation; END IF;
    RETURN QUERY SELECT result.funding_kind,result.recorded_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_funding.record_funding(text,text,bigint,uuid,uuid,uuid,uuid,uuid,uuid) FROM PUBLIC;
