-- Separate answer-only capability. Existing readers remain read-only.
CREATE SCHEMA omnixat_customer_answers;
REVOKE ALL ON SCHEMA omnixat_customer_answers FROM PUBLIC;
CREATE FUNCTION omnixat_customer_answers.answer_csv(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, job uuid, expected_actor uuid,
    answer_field text, answer_row integer, answer_column integer, answer_amount text
) RETURNS TABLE (outcome text, stored_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE actor uuid;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),
            set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject
        AND i.disabled_at IS NULL AND issued_at>i.tokens_valid_after AND i.actor_kind='human'
        AND m.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND m.revoked_at IS NULL AND m.role IN ('owner','editor');
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    -- Validate even when invoked directly through the execute-only database role.
    IF answer_field IS NULL OR answer_field COLLATE "C" !~ '^[a-z][a-z0-9_]{0,63}$'
       OR answer_row IS NULL OR answer_row NOT BETWEEN 1 AND 5000
       OR answer_column IS NULL OR answer_column NOT BETWEEN 1 AND 64
       OR (answer_amount IS NOT NULL AND answer_amount COLLATE "C" !~ '^[+-]?[0-9]{1,18}(\.[0-9]{1,6})?$') THEN
        RAISE invalid_parameter_value;
    END IF;
    -- Existing validated service binds exact job/cell, current source/policy and
    -- immutable answer retry/conflict. Attribution is never supplied by clients.
    RETURN QUERY SELECT a.outcome,a.stored_at FROM omnixat_extraction.store_csv_answer(
        organisation,evidence,job,answer_field,answer_row,answer_column,answer_amount,actor::text) a;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_answers.answer_csv(text,text,bigint,uuid,uuid,uuid,uuid,text,integer,integer,text) FROM PUBLIC;
