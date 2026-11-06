CREATE SCHEMA omnixat_extraction;
REVOKE ALL ON SCHEMA omnixat_extraction FROM PUBLIC;

-- Empty means extraction is disabled. Only an operator may set the policy.
CREATE TABLE omnixat_extraction.active_scan_policy (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    policy_version text NOT NULL CHECK (
        policy_version COLLATE "C" ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$'
    )
);
REVOKE ALL ON omnixat_extraction.active_scan_policy FROM PUBLIC;

-- Keep configuration, eligibility and original bytes on one statement snapshot.
CREATE FUNCTION omnixat_extraction.read_eligible_original(organisation uuid, evidence uuid)
RETURNS TABLE (policy_version text, media_type text, content_sha256 bytea, byte_size integer, original_bytes bytea)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
    SELECT p.policy_version, r.media_type, q.content_sha256, q.byte_size, q.original_bytes
    FROM omnixat_extraction.active_scan_policy p
    CROSS JOIN omnixat.evidence_quarantine q
    JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
    WHERE q.tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
      AND q.evidence_id = evidence AND r.organisation_id = organisation
      AND EXISTS (
          SELECT 1 FROM omnixat.evidence_scan_verdicts v
          WHERE (v.tenant_id, v.evidence_id, v.content_sha256, v.byte_size, v.policy_version) =
                (q.tenant_id, q.evidence_id, q.content_sha256, q.byte_size, p.policy_version)
            AND v.verdict = 'clean'
      )
      AND NOT EXISTS (
          SELECT 1 FROM omnixat.evidence_scan_verdicts v
          WHERE (v.tenant_id, v.evidence_id, v.policy_version) =
                (q.tenant_id, q.evidence_id, p.policy_version)
            AND v.verdict = 'blocked'
      )
      AND NOT EXISTS (
          SELECT 1 FROM omnixat.evidence_scan_claims c
          WHERE (c.tenant_id, c.evidence_id, c.policy_version) =
                (q.tenant_id, q.evidence_id, p.policy_version)
            AND c.expires_at > statement_timestamp()
      );
$$;

REVOKE ALL ON FUNCTION omnixat_extraction.read_eligible_original(uuid, uuid) FROM PUBLIC;
