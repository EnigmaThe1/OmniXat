CREATE SCHEMA omnixat_customer_preparation;
REVOKE ALL ON SCHEMA omnixat_customer_preparation FROM PUBLIC;

-- Row-locking SELECT needs UPDATE visibility under RLS. These policies permit
-- locking only the current identity/membership, while WITH CHECK(false) still
-- forbids actual updates. Runtime logins receive no direct UPDATE grants.
CREATE POLICY preparation_identity_lock ON omnixat.identities FOR UPDATE
    USING (issuer=current_setting('omnixat.issuer',true) AND subject=current_setting('omnixat.subject',true))
    WITH CHECK (false);
CREATE POLICY preparation_membership_lock ON omnixat.memberships FOR UPDATE
    USING (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND user_id IN (SELECT id FROM omnixat.identities))
    WITH CHECK (false);

-- Choices are bookkeeping configuration, not proof of source eligibility.
CREATE FUNCTION omnixat_customer_preparation.expense_choices(
    requested_issuer text, requested_subject text, issued_at bigint, organisation uuid, evidence uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    IF NOT EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
        WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
          AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
          AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor')) THEN
        RAISE insufficient_privilege;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.evidence_registrations r
        WHERE r.tenant_id=tenant AND r.organisation_id=organisation AND r.id=evidence) THEN
        RETURN NULL;
    END IF;
    RETURN jsonb_build_object(
        'periods', (SELECT coalesce(jsonb_agg(to_jsonb(p)),'[]'::jsonb) FROM (
            SELECT id,starts_on,ends_on FROM omnixat.expense_accounting_periods
            WHERE tenant_id=tenant AND organisation_id=organisation AND open_for_drafts
            ORDER BY starts_on DESC,id DESC LIMIT 21) p),
        'accounts', (SELECT coalesce(jsonb_agg(to_jsonb(a)),'[]'::jsonb) FROM (
            SELECT account_id AS id FROM omnixat.expense_account_policy
            WHERE tenant_id=tenant AND organisation_id=organisation AND eligible_for_drafts
            ORDER BY account_id LIMIT 21) a));
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_preparation.expense_choices(text,text,bigint,uuid,uuid) FROM PUBLIC;

CREATE FUNCTION omnixat_customer_preparation.create_expense(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, job uuid, expected_actor uuid,
    requested_field text, requested_row integer, requested_column integer,
    period uuid, account uuid, requested_date date
) RETURNS TABLE (draft_id uuid,stored_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
SET lock_timeout = '1s'
AS $$ DECLARE actor uuid; amount_result record; expense_result record;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
        WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
          AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
          AND m.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
          AND m.revoked_at IS NULL AND m.role IN ('owner','editor')
        FOR SHARE OF i,m;
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR actor<>expected_actor THEN RAISE no_data_found; END IF;
    IF job IS NULL OR period IS NULL OR account IS NULL OR requested_date IS NULL
       OR requested_field IS NULL OR requested_field COLLATE "C" !~ '^[a-z][a-z0-9_]{0,63}$'
       OR requested_row IS NULL OR requested_row NOT BETWEEN 1 AND 5000
       OR requested_column IS NULL OR requested_column NOT BETWEEN 1 AND 64 THEN
        RAISE invalid_parameter_value;
    END IF;
    SELECT * INTO amount_result FROM omnixat_extraction.create_csv_draft_amount(
        organisation,evidence,job,requested_field,requested_row,requested_column,actor::text);
    IF amount_result.outcome='conflict' THEN RAISE unique_violation; END IF;
    IF amount_result.outcome IS DISTINCT FROM 'stored' THEN RAISE check_violation; END IF;
    SELECT * INTO expense_result FROM omnixat_extraction.create_csv_expense_draft(
        organisation,evidence,job,requested_field,requested_row,requested_column,
        period,account,requested_date,'GBP',actor::text);
    IF expense_result.outcome='conflict' THEN RAISE unique_violation; END IF;
    IF expense_result.outcome IN ('context','amount') THEN RAISE invalid_parameter_value; END IF;
    IF expense_result.outcome IS DISTINCT FROM 'stored' THEN RAISE check_violation; END IF;
    -- Exceptions above roll back the source amount too. A rejected preparation
    -- must never leave a new partial amount draft behind.
    RETURN QUERY SELECT expense_result.draft_id,expense_result.stored_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_preparation.create_expense(text,text,bigint,uuid,uuid,uuid,uuid,text,integer,integer,uuid,uuid,date) FROM PUBLIC;
