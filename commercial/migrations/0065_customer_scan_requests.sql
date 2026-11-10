-- Separate write capability: no payload, scanner, policy or verdict mutation.
CREATE TABLE omnixat.evidence_scan_requests (
    tenant_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    policy_version text NOT NULL CHECK (policy_version COLLATE "C" ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$'),
    requested_by uuid NOT NULL REFERENCES omnixat.identities(id),
    requested_issuer text NOT NULL,
    requested_subject text NOT NULL,
    authorised_iat bigint NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,evidence_id,policy_version),
    FOREIGN KEY (tenant_id,evidence_id) REFERENCES omnixat.evidence_registrations(tenant_id,id)
);
ALTER TABLE omnixat.evidence_scan_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_scan_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_scan_requests
    USING (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid)
    WITH CHECK (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid);
REVOKE ALL ON omnixat.evidence_scan_requests FROM PUBLIC;
CREATE SCHEMA omnixat_evidence_requests;
REVOKE ALL ON SCHEMA omnixat_evidence_requests FROM PUBLIC;

CREATE FUNCTION omnixat_evidence_requests.request_scan(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, expected_actor uuid
) RETURNS TABLE (evidence_id uuid, policy_version text, requested_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE actor uuid; policy text; tenant uuid;
BEGIN
    tenant:=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    PERFORM set_config('omnixat.issuer',requested_issuer,true),
            set_config('omnixat.subject',requested_subject,true);
    -- Resolve persisted authority on each invocation; token roles cannot grant it.
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject
        AND i.disabled_at IS NULL AND issued_at>i.tokens_valid_after AND i.actor_kind='human'
        AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor');
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NOT NULL AND expected_actor<>actor THEN
        RAISE no_data_found; -- Actor continuity conflict; never an authorisation grant.
    END IF;
    -- Lock the operator-selected policy through insertion. Clients cannot choose it.
    SELECT p.policy_version INTO policy FROM omnixat_extraction.active_scan_policy p
      WHERE p.singleton FOR SHARE;
    IF policy IS NULL THEN RETURN; END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.evidence_registrations r
      JOIN omnixat.evidence_quarantine q ON (q.tenant_id,q.evidence_id)=(r.tenant_id,r.id)
      WHERE r.tenant_id=tenant AND r.organisation_id=organisation AND r.id=evidence) THEN RETURN; END IF;
    INSERT INTO omnixat.evidence_scan_requests AS existing
      (tenant_id,evidence_id,policy_version,requested_by,requested_issuer,requested_subject,authorised_iat)
      VALUES (tenant,evidence,policy,actor,requested_issuer,requested_subject,issued_at) ON CONFLICT DO NOTHING;
    -- READ COMMITTED sees the winning insert after a concurrent retry waits.
    RETURN QUERY SELECT s.evidence_id,s.policy_version,s.requested_at
      FROM omnixat.evidence_scan_requests s
      WHERE s.tenant_id=tenant AND s.evidence_id=evidence AND s.policy_version=policy;
END $$;
REVOKE ALL ON FUNCTION omnixat_evidence_requests.request_scan(text,text,bigint,uuid,uuid,uuid) FROM PUBLIC;

-- Explicit worker admission: a current-policy request and still-authorised human.
-- No original bytes, pending-tenant enumeration or ability to select another policy.
CREATE FUNCTION omnixat_evidence_requests.worker_request(organisation uuid, evidence uuid)
RETURNS TABLE (policy_version text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE request omnixat.evidence_scan_requests%ROWTYPE;
BEGIN
    SELECT s.* INTO request FROM omnixat.evidence_scan_requests s
      JOIN omnixat_extraction.active_scan_policy p ON p.singleton AND p.policy_version=s.policy_version
      WHERE s.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid AND s.evidence_id=evidence;
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM set_config('omnixat.issuer',request.requested_issuer,true),
            set_config('omnixat.subject',request.requested_subject,true);
    RETURN QUERY SELECT s.policy_version FROM omnixat.evidence_scan_requests s
    JOIN omnixat.evidence_registrations r ON (r.tenant_id,r.id)=(s.tenant_id,s.evidence_id)
    JOIN omnixat_extraction.active_scan_policy p ON p.singleton AND p.policy_version=s.policy_version
    WHERE s.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
      AND r.organisation_id=organisation AND r.id=evidence
      AND EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
        WHERE i.id=s.requested_by AND i.disabled_at IS NULL AND i.actor_kind='human'
          AND s.authorised_iat>i.tokens_valid_after
          AND m.user_id=s.requested_by AND m.tenant_id=s.tenant_id AND m.revoked_at IS NULL
          AND m.role IN ('owner','editor'));
END $$;
REVOKE ALL ON FUNCTION omnixat_evidence_requests.worker_request(uuid,uuid) FROM PUBLIC;

-- Keep the existing read-only status signature and grants.
CREATE OR REPLACE FUNCTION omnixat_evidence_status.read_status(
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
             WHEN EXISTS (SELECT 1 FROM omnixat.evidence_scan_requests s
                WHERE (s.tenant_id,s.evidence_id,s.policy_version)=(r.tenant_id,r.id,p.policy_version)) THEN 'requested'
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
