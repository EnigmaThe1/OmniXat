-- Structured correction requests and inspection; no amount change or approval.
CREATE SCHEMA omnixat_customer_corrections;
REVOKE ALL ON SCHEMA omnixat_customer_corrections FROM PUBLIC;
CREATE FUNCTION omnixat_customer_corrections.inspect(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_snapshot bytea, after_reviewer text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    actor uuid; member_role text; result jsonb;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id,m.role INTO actor,member_role FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after AND m.tenant_id=tenant AND m.revoked_at IS NULL;
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_snapshot IS NULL OR octet_length(expected_snapshot)<>32
       OR after_reviewer IS NOT NULL AND (char_length(after_reviewer) NOT BETWEEN 1 AND 200 OR btrim(after_reviewer)='') THEN RAISE invalid_parameter_value; END IF;
    -- Eligibility, saved fingerprint, own prerequisite and page share one statement snapshot.
    SELECT jsonb_build_object('journal_id',j.journal_id,'snapshot_sha256',encode(j.snapshot_sha256,'hex'),
      'actor_id',actor,'can_request',member_role IN ('owner','editor'),
      'own',(SELECT jsonb_build_object('decision',o.decision,'reason',c.reason,'recorded_at',c.recorded_at)
        FROM omnixat.expense_journal_review_decisions o LEFT JOIN omnixat.expense_journal_correction_requests c
        USING(tenant_id,organisation_id,journal_id,snapshot_sha256,reviewer_id)
        WHERE o.tenant_id=tenant AND o.organisation_id=organisation AND o.journal_id=j.journal_id
          AND o.snapshot_sha256=j.snapshot_sha256 AND o.reviewer_id=actor::text),
      'items',coalesce((SELECT jsonb_agg(to_jsonb(p)||jsonb_build_object('clarification_recorded',EXISTS(
          SELECT 1 FROM omnixat.expense_journal_clarification_answers a WHERE a.tenant_id=tenant
            AND a.organisation_id=organisation AND a.journal_id=j.journal_id
            AND a.snapshot_sha256=j.snapshot_sha256 AND a.reason=p.correction_reason)) ORDER BY p.reviewer_id)
        FROM omnixat_extraction.read_expense_journal_decisions_with_corrections(organisation,j.journal_id,expected_snapshot,after_reviewer,20) p
        WHERE p.reviewer_id IS NOT NULL),'[]'::jsonb)) INTO result
    FROM omnixat.csv_expense_drafts d JOIN omnixat.expense_journal_drafts s
      ON (s.tenant_id,s.organisation_id,s.expense_draft_id)=(d.tenant_id,d.organisation_id,d.id)
    CROSS JOIN LATERAL omnixat_extraction.read_expense_journal_review(organisation,s.id) j
    WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft;
    IF result IS NULL THEN RETURN NULL; END IF;
    IF result->>'snapshot_sha256'<>encode(expected_snapshot,'hex') THEN RAISE serialization_failure; END IF;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_corrections.inspect(text,text,bigint,uuid,uuid,uuid,bytea,text) FROM PUBLIC;

CREATE FUNCTION omnixat_customer_corrections.record_reason(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_actor uuid,
    expected_snapshot bytea, requested_reason text
) RETURNS TABLE (journal_id uuid,recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on SET lock_timeout = '1s'
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    actor uuid; saved_journal uuid; gated record; result record;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after AND m.tenant_id=tenant
        AND m.revoked_at IS NULL AND m.role IN ('owner','editor') FOR SHARE OF i,m;
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    IF expected_snapshot IS NULL OR octet_length(expected_snapshot)<>32 OR requested_reason IS NULL
      OR requested_reason NOT IN ('amount','account','funding','accounting_date','source_evidence') THEN RAISE invalid_parameter_value; END IF;
    -- Require and retain the caller's existing observation before invoking the shared
    -- gate. The nested retry must never create an observation implicitly.
    SELECT j.id INTO saved_journal FROM omnixat.csv_expense_drafts d JOIN omnixat.expense_journal_drafts j
      ON (j.tenant_id,j.organisation_id,j.expense_draft_id)=(d.tenant_id,d.organisation_id,d.id)
    JOIN omnixat.expense_journal_review_decisions o ON (o.tenant_id,o.organisation_id,o.journal_id)=(j.tenant_id,j.organisation_id,j.id)
    WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft
      AND o.snapshot_sha256=expected_snapshot AND o.reviewer_id=actor::text AND o.decision='changes_requested'
    FOR SHARE OF o;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    -- Reuse exact-snapshot validation and identity/source/scan/funding/accounting
    -- locks from the observation boundary. Existing same-choice receipt is a no-op.
    SELECT * INTO gated FROM omnixat_customer_journal_decisions.record_observation(
      requested_issuer,requested_subject,issued_at,organisation,evidence,requested_draft,actor,expected_snapshot,'changes_requested');
    IF gated.journal_id IS DISTINCT FROM saved_journal THEN RAISE check_violation; END IF;
    SELECT * INTO result FROM omnixat_extraction.record_expense_journal_correction(
      organisation,saved_journal,expected_snapshot,requested_reason,actor::text);
    IF result.outcome='conflict' THEN RAISE unique_violation; END IF;
    IF result.outcome IS DISTINCT FROM 'stored' THEN RAISE check_violation; END IF;
    RETURN QUERY SELECT saved_journal,result.correction_recorded_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_corrections.record_reason(text,text,bigint,uuid,uuid,uuid,uuid,bytea,text) FROM PUBLIC;
