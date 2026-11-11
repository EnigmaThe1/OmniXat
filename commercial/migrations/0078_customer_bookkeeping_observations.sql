-- Historical bookkeeping observations only. No posting, correction or filing approval.
CREATE SCHEMA omnixat_customer_journal_decisions;
REVOKE ALL ON SCHEMA omnixat_customer_journal_decisions FROM PUBLIC;
CREATE FUNCTION omnixat_customer_journal_decisions.record_observation(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_actor uuid,
    expected_snapshot bytea, requested_decision text
) RETURNS TABLE (journal_id uuid,recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on SET lock_timeout = '1s'
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    actor uuid; active_policy text; saved_journal uuid; result record; current_snapshot bytea;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
    WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
      AND i.actor_kind='human' AND issued_at>i.tokens_valid_after AND m.tenant_id=tenant
      AND m.revoked_at IS NULL AND m.role IN ('owner','editor') FOR SHARE OF i,m;
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    IF expected_snapshot IS NULL OR octet_length(expected_snapshot)<>32
       OR requested_decision IS NULL OR requested_decision NOT IN ('reviewed','changes_requested') THEN RAISE invalid_parameter_value; END IF;
    -- Match the shared journal writer's policy/context/quarantine/source lock order.
    -- Keep each current gate and the saved snapshot stable through observation commit.
    SELECT p.policy_version INTO active_policy FROM omnixat_extraction.active_scan_policy p FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    SELECT j.id INTO saved_journal FROM omnixat.csv_expense_drafts d
    JOIN omnixat.expense_journal_drafts j ON (j.tenant_id,j.organisation_id,j.expense_draft_id)=(d.tenant_id,d.organisation_id,d.id)
    JOIN omnixat.expense_accounting_periods p ON (p.tenant_id,p.organisation_id,p.id)=(d.tenant_id,d.organisation_id,d.period_id)
    JOIN omnixat.expense_account_policy a ON (a.tenant_id,a.organisation_id,a.account_id)=(d.tenant_id,d.organisation_id,d.expense_account_id)
    JOIN omnixat.expense_funding_context f ON (f.tenant_id,f.organisation_id,f.draft_id)=(d.tenant_id,d.organisation_id,d.id)
    JOIN omnixat.expense_funding_sources s ON (s.tenant_id,s.organisation_id,s.id)=(f.tenant_id,f.organisation_id,f.funding_source_id)
    JOIN omnixat.expense_counterpart_policy c ON (c.tenant_id,c.organisation_id,c.funding_source_id,c.account_id)=
        (j.tenant_id,j.organisation_id,j.funding_source_id,j.counterpart_account_id)
    WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft
      AND p.open_for_drafts AND a.eligible_for_drafts AND s.eligible_for_drafts AND c.eligible_for_drafts
    FOR SHARE OF d,j,p,a,f,s,c;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    PERFORM 1 FROM omnixat.evidence_quarantine q JOIN omnixat.evidence_registrations r
      ON (r.tenant_id,r.id)=(q.tenant_id,q.evidence_id)
      WHERE q.tenant_id=tenant AND q.evidence_id=evidence AND r.organisation_id=organisation
      FOR UPDATE OF q FOR SHARE OF r;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    PERFORM 1 FROM omnixat.evidence_scan_claims c WHERE c.tenant_id=tenant AND c.evidence_id=evidence
      AND c.policy_version=active_policy FOR SHARE NOWAIT;
    PERFORM 1 FROM omnixat.csv_expense_drafts d JOIN omnixat.evidence_draft_amounts a USING(tenant_id,job_id,field_name)
      JOIN omnixat.csv_extraction_results r ON (r.tenant_id,r.job_id)=(d.tenant_id,d.job_id)
      WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.id=requested_draft FOR SHARE OF a,r;
    IF NOT FOUND THEN RAISE check_violation; END IF;
    SELECT j.snapshot_sha256 INTO current_snapshot FROM omnixat_extraction.read_expense_journal_review(organisation,saved_journal) j;
    IF current_snapshot IS NULL THEN RAISE check_violation; END IF;
    IF current_snapshot<>expected_snapshot THEN RAISE serialization_failure; END IF;
    SELECT * INTO result FROM omnixat_extraction.record_expense_journal_decision(
      organisation,saved_journal,expected_snapshot,requested_decision,actor::text);
    IF result.outcome='conflict' THEN RAISE unique_violation; END IF;
    IF result.outcome IS DISTINCT FROM 'stored' THEN RAISE check_violation; END IF;
    RETURN QUERY SELECT saved_journal,result.decision_recorded_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_journal_decisions.record_observation(text,text,bigint,uuid,uuid,uuid,uuid,bytea,text) FROM PUBLIC;
