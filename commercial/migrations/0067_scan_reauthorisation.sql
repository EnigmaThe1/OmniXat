-- Append-only through runtime capabilities; no direct history grants.
CREATE TABLE omnixat.evidence_scan_request_history (
    tenant_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    policy_version text NOT NULL,
    cancelled_at timestamptz NOT NULL,
    previous_request jsonb NOT NULL,
    reauthorised_by uuid NOT NULL REFERENCES omnixat.identities(id),
    reauthorised_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id,evidence_id,policy_version,cancelled_at),
    FOREIGN KEY (tenant_id,evidence_id,policy_version)
      REFERENCES omnixat.evidence_scan_requests(tenant_id,evidence_id,policy_version)
);
ALTER TABLE omnixat.evidence_scan_request_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.evidence_scan_request_history FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.evidence_scan_request_history
    USING (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid)
    WITH CHECK (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid);
REVOKE ALL ON omnixat.evidence_scan_request_history FROM PUBLIC;
CREATE FUNCTION omnixat_evidence_requests.reauthorise_scan(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, expected_actor uuid, cancellation timestamptz
) RETURNS TABLE (evidence_id uuid, policy_version text, requested_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE actor uuid; policy text; tenant uuid; previous omnixat.evidence_scan_requests%ROWTYPE; renewed timestamptz;
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
    -- Lock the operator-selected policy through re-authorisation. Clients cannot choose it.
    SELECT p.policy_version INTO policy FROM omnixat_extraction.active_scan_policy p
      WHERE p.singleton FOR SHARE;
    IF policy IS NULL THEN RETURN; END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.evidence_registrations r
      JOIN omnixat.evidence_quarantine q ON (q.tenant_id,q.evidence_id)=(r.tenant_id,r.id)
      WHERE r.tenant_id=tenant AND r.organisation_id=organisation AND r.id=evidence) THEN RETURN; END IF;
    IF cancellation IS NULL THEN RETURN; END IF;
    SELECT s.* INTO previous FROM omnixat.evidence_scan_requests s
      WHERE s.tenant_id=tenant AND s.evidence_id=evidence AND s.policy_version=policy FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    IF previous.cancelled_at IS NULL THEN
        IF NOT EXISTS (SELECT 1 FROM omnixat.evidence_scan_request_history h
          WHERE (h.tenant_id,h.evidence_id,h.policy_version,h.cancelled_at)=
                (tenant,evidence,policy,cancellation) AND h.reauthorised_at=previous.requested_at) THEN RETURN; END IF;
    ELSE
        IF previous.cancelled_at<>cancellation THEN RETURN; END IF;
        renewed:=clock_timestamp();
        INSERT INTO omnixat.evidence_scan_request_history
          (tenant_id,evidence_id,policy_version,cancelled_at,previous_request,reauthorised_by,reauthorised_at)
          VALUES (tenant,evidence,policy,cancellation,to_jsonb(previous),actor,renewed);
        UPDATE omnixat.evidence_scan_requests AS s
          SET requested_by=actor,requested_issuer=reauthorise_scan.requested_issuer,
              requested_subject=reauthorise_scan.requested_subject,authorised_iat=issued_at,
              requested_at=renewed,cancelled_at=NULL,cancelled_by=NULL
          WHERE s.tenant_id=tenant AND s.evidence_id=evidence AND s.policy_version=policy;
    END IF;
    RETURN QUERY SELECT s.evidence_id,s.policy_version,s.requested_at
      FROM omnixat.evidence_scan_requests s
      WHERE s.tenant_id=tenant AND s.evidence_id=evidence AND s.policy_version=policy;
END $$;
REVOKE ALL ON FUNCTION omnixat_evidence_requests.reauthorise_scan(text,text,bigint,uuid,uuid,uuid,timestamptz) FROM PUBLIC;

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
                WHERE (s.tenant_id,s.evidence_id,s.policy_version)=(r.tenant_id,r.id,p.policy_version) AND s.cancelled_at IS NOT NULL) THEN 'cancelled'
             WHEN EXISTS (SELECT 1 FROM omnixat.evidence_scan_requests s
                WHERE (s.tenant_id,s.evidence_id,s.policy_version)=(r.tenant_id,r.id,p.policy_version)) THEN 'requested'
             ELSE 'awaiting_scan' END,
        CASE WHEN q.evidence_id IS NULL THEN NULL
             WHEN v.blocked_at IS NOT NULL THEN v.blocked_at
             WHEN live.claimed THEN NULL
             WHEN v.clean_at IS NOT NULL THEN v.clean_at
             ELSE (SELECT s.cancelled_at FROM omnixat.evidence_scan_requests s
               WHERE (s.tenant_id,s.evidence_id,s.policy_version)=(r.tenant_id,r.id,p.policy_version)) END
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
