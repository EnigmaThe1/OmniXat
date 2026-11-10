-- Metadata-only capability. No originals, lease tokens or mutation functions.
CREATE SCHEMA omnixat_evidence_status;
REVOKE ALL ON SCHEMA omnixat_evidence_status FROM PUBLIC;
CREATE FUNCTION omnixat_evidence_status.read_status(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid
) RETURNS TABLE (evidence_id uuid, policy_version text, status text, recorded_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),
            set_config('omnixat.subject',requested_subject,true);
    RETURN QUERY
    SELECT r.id,p.policy_version,
        CASE WHEN q.evidence_id IS NULL THEN 'upload_incomplete'
             WHEN p.policy_version IS NULL THEN 'not_configured'
             WHEN v.blocked_at IS NOT NULL THEN 'blocked'
             WHEN live.claimed THEN 'scanning'
             WHEN v.clean_at IS NOT NULL THEN 'scanned'
             ELSE 'awaiting_scan' END,
        CASE WHEN v.blocked_at IS NOT NULL THEN v.blocked_at
             WHEN NOT live.claimed THEN v.clean_at ELSE NULL END
    FROM omnixat.evidence_registrations r
    LEFT JOIN omnixat.evidence_quarantine q ON (q.tenant_id,q.evidence_id)=(r.tenant_id,r.id)
    LEFT JOIN omnixat_extraction.active_scan_policy p ON p.singleton
    LEFT JOIN LATERAL (
        SELECT max(s.recorded_at) FILTER (WHERE s.verdict='blocked') AS blocked_at,
               max(s.recorded_at) FILTER (WHERE s.verdict='clean') AS clean_at
        FROM omnixat.evidence_scan_verdicts s
        WHERE (s.tenant_id,s.evidence_id,s.content_sha256,s.byte_size,s.policy_version)=
              (q.tenant_id,q.evidence_id,q.content_sha256,q.byte_size,p.policy_version)
    ) v ON true
    LEFT JOIN LATERAL (SELECT EXISTS (
        SELECT 1 FROM omnixat.evidence_scan_claims c
        WHERE (c.tenant_id,c.evidence_id,c.policy_version)=(r.tenant_id,r.id,p.policy_version)
          AND c.expires_at>statement_timestamp()) AS claimed
    ) live ON true
    WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
      AND r.organisation_id=organisation AND r.id=evidence
      AND EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
          WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
            AND issued_at>i.tokens_valid_after AND m.tenant_id=r.tenant_id AND m.revoked_at IS NULL);
END $$;
REVOKE ALL ON FUNCTION omnixat_evidence_status.read_status(text,text,bigint,uuid,uuid) FROM PUBLIC;
