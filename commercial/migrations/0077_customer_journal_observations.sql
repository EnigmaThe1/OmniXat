-- Inspection of historical bookkeeping observations, never filing approval.
CREATE SCHEMA omnixat_customer_journal_reviews;
REVOKE ALL ON SCHEMA omnixat_customer_journal_reviews FROM PUBLIC;
CREATE FUNCTION omnixat_customer_journal_reviews.read_observations(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid, expected_snapshot bytea,
    after_reviewer text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET row_security = on
AS $$ DECLARE
    tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    result jsonb;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    IF NOT EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
        AND m.tenant_id=tenant AND m.revoked_at IS NULL) THEN RAISE insufficient_privilege; END IF;
    IF expected_snapshot IS NULL OR octet_length(expected_snapshot)<>32
      OR after_reviewer IS NOT NULL AND (char_length(after_reviewer) NOT BETWEEN 1 AND 200 OR btrim(after_reviewer)='')
      THEN RAISE invalid_parameter_value; END IF;
    -- One statement snapshot binds the source/context eligibility, saved journal,
    -- fingerprint and bounded observation page together. Never infer an empty
    -- history from an unavailable or changed saved journal.
    SELECT jsonb_build_object('journal_id',j.journal_id,'snapshot_sha256',encode(j.snapshot_sha256,'hex'),
        'items',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.reviewer_id)
          FROM omnixat_extraction.read_expense_journal_decisions(organisation,j.journal_id,expected_snapshot,after_reviewer,20) p
          WHERE p.reviewer_id IS NOT NULL),'[]'::jsonb)) INTO result
    FROM omnixat.csv_expense_drafts d JOIN omnixat.expense_journal_drafts s
      ON (s.tenant_id,s.organisation_id,s.expense_draft_id)=(d.tenant_id,d.organisation_id,d.id)
    CROSS JOIN LATERAL omnixat_extraction.read_expense_journal_review(organisation,s.id) j
    WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence AND d.id=requested_draft;
    IF result IS NULL THEN RETURN NULL; END IF;
    IF result->>'snapshot_sha256'<>encode(expected_snapshot,'hex') THEN RAISE no_data_found; END IF;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_journal_reviews.read_observations(text,text,bigint,uuid,uuid,uuid,bytea,text) FROM PUBLIC;
