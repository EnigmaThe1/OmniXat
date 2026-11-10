-- A fresh linked request preserves the cancelled parent's immutable history.
ALTER TABLE omnixat.csv_extraction_requests
    ADD COLUMN previous_job_id uuid,
    ADD CONSTRAINT csv_request_previous_job FOREIGN KEY (tenant_id,previous_job_id)
      REFERENCES omnixat.csv_extraction_requests(tenant_id,job_id),
    ADD CONSTRAINT csv_request_one_replacement UNIQUE (tenant_id,previous_job_id),
    ADD CONSTRAINT csv_request_not_own_parent CHECK (previous_job_id IS DISTINCT FROM job_id);

CREATE FUNCTION omnixat_csv_requests.reauthorise_csv(
    requested_issuer text,requested_subject text,issued_at bigint,
    organisation uuid,evidence uuid,job uuid,new_job uuid,
    expected_cancellation timestamptz,expected_actor uuid
) RETURNS TABLE (job_id uuid,policy_version text,requested_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE actor uuid; tenant uuid; parent omnixat.csv_extraction_requests%ROWTYPE;
    child omnixat.csv_extraction_requests%ROWTYPE; receipt record;
BEGIN
    tenant:=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
        AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor');
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR actor<>expected_actor THEN RAISE no_data_found; END IF;
    IF new_job IS NULL OR new_job=job OR expected_cancellation IS NULL THEN RAISE invalid_parameter_value; END IF;
    SELECT r.* INTO parent FROM omnixat.csv_extraction_requests r
      WHERE r.tenant_id=tenant AND r.organisation_id=organisation AND r.evidence_id=evidence AND r.job_id=job FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    IF parent.cancelled_at IS NULL OR parent.cancelled_at IS DISTINCT FROM expected_cancellation THEN RETURN; END IF;
    SELECT r.* INTO child FROM omnixat.csv_extraction_requests r
      WHERE r.tenant_id=tenant AND r.previous_job_id=job;
    IF FOUND THEN
        -- Reconcile this exact attempt; never restart a child cancelled afterwards.
        IF child.job_id<>new_job OR child.requested_by<>actor THEN RAISE unique_violation; END IF;
        RETURN QUERY SELECT child.job_id,child.policy_version,child.requested_at; RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM omnixat.csv_extraction_results r WHERE r.tenant_id=tenant AND r.job_id=job) THEN RETURN; END IF;
    IF EXISTS (SELECT 1 FROM omnixat.csv_extraction_requests r WHERE r.tenant_id=tenant AND r.job_id=new_job) THEN
        RAISE unique_violation; -- Never adopt an unrelated existing request.
    END IF;
    SELECT * INTO receipt FROM omnixat_csv_requests.request_csv(requested_issuer,requested_subject,issued_at,
        organisation,evidence,new_job,expected_actor,parent.selections);
    IF NOT FOUND THEN RETURN; END IF;
    UPDATE omnixat.csv_extraction_requests r SET previous_job_id=job
      WHERE r.tenant_id=tenant AND r.job_id=new_job;
    RETURN QUERY SELECT receipt.job_id,receipt.policy_version,receipt.requested_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_requests.reauthorise_csv(text,text,bigint,uuid,uuid,uuid,uuid,timestamptz,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION omnixat_csv_request_status.read_requests(
    requested_issuer text,requested_subject text,issued_at bigint,
    organisation uuid,evidence uuid,job uuid
) RETURNS TABLE (job_id uuid,policy_version text,selections jsonb,requested_by uuid,requested_at timestamptz,
                 cancelled_by uuid,cancelled_at timestamptz,state text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    IF NOT EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
        WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
          AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
          AND m.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid AND m.revoked_at IS NULL)
        THEN RAISE insufficient_privilege; END IF;
    RETURN QUERY SELECT r.job_id,r.policy_version,r.selections,r.requested_by,r.requested_at,r.cancelled_by,r.cancelled_at,
        CASE WHEN r.cancelled_at IS NOT NULL AND EXISTS (SELECT 1 FROM omnixat.csv_extraction_requests child
                  WHERE child.tenant_id=r.tenant_id AND child.previous_job_id=r.job_id) THEN 'reauthorised'
             WHEN r.cancelled_at IS NOT NULL THEN 'cancelled'
             WHEN x.job_id IS NOT NULL THEN 'result_recorded' ELSE 'awaiting_worker' END
      FROM omnixat.csv_extraction_requests r
      JOIN omnixat.evidence_registrations e ON (e.tenant_id,e.id,e.organisation_id)=(r.tenant_id,r.evidence_id,r.organisation_id)
      LEFT JOIN omnixat.csv_extraction_results x ON (x.tenant_id,x.job_id)=(r.tenant_id,r.job_id)
      WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND r.organisation_id=organisation AND r.evidence_id=evidence AND (job IS NULL OR r.job_id=job)
      ORDER BY r.requested_at DESC,r.job_id DESC LIMIT 21;
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_request_status.read_requests(text,text,bigint,uuid,uuid,uuid) FROM PUBLIC;
