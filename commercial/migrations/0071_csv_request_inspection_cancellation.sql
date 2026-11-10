ALTER TABLE omnixat.csv_extraction_requests
    ADD COLUMN cancelled_at timestamptz,
    ADD COLUMN cancelled_by uuid REFERENCES omnixat.identities(id),
    ADD CONSTRAINT complete_csv_cancellation CHECK ((cancelled_at IS NULL)=(cancelled_by IS NULL));
CREATE INDEX csv_request_evidence_latest ON omnixat.csv_extraction_requests
    (tenant_id,organisation_id,evidence_id,requested_at DESC,job_id DESC);

CREATE OR REPLACE FUNCTION omnixat_csv_requests.worker_request(organisation uuid,evidence uuid,job uuid,selected_cells jsonb)
RETURNS TABLE (policy_version text,content_sha256 bytea)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE request omnixat.csv_extraction_requests%ROWTYPE;
BEGIN
    SELECT r.* INTO request FROM omnixat.csv_extraction_requests r
      WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND r.job_id=job AND r.organisation_id=organisation AND r.evidence_id=evidence AND r.selections=selected_cells AND r.cancelled_at IS NULL;
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM set_config('omnixat.issuer',request.requested_issuer,true),set_config('omnixat.subject',request.requested_subject,true);
    RETURN QUERY SELECT a.policy_version,a.content_sha256
      FROM omnixat_extraction.read_eligible_original(organisation,evidence) a
      WHERE (a.policy_version,a.content_sha256,a.byte_size)=(request.policy_version,request.content_sha256,request.byte_size)
        AND a.media_type='text/csv'
        AND EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
          WHERE i.id=request.requested_by AND i.disabled_at IS NULL AND i.actor_kind='human'
            AND request.authorised_iat>i.tokens_valid_after AND m.tenant_id=request.tenant_id
            AND m.revoked_at IS NULL AND m.role IN ('owner','editor'));
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_requests.worker_request(uuid,uuid,uuid,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION omnixat_csv_requests.store_requested_result(
    organisation uuid,evidence uuid,job uuid,selected_cells jsonb,
    expected_policy text,expected_digest bytea,result_amounts jsonb
) RETURNS TABLE (outcome text,stored_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ BEGIN
    -- Cancellation and requested result storage share this row lock until commit.
    PERFORM 1 FROM omnixat.csv_extraction_requests r
      WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND r.job_id=job AND r.organisation_id=organisation AND r.evidence_id=evidence FOR UPDATE;
    IF NOT FOUND THEN RETURN QUERY SELECT 'ineligible'::text,NULL::timestamptz; RETURN; END IF;
    PERFORM 1 FROM omnixat_extraction.active_scan_policy p WHERE p.policy_version=expected_policy FOR SHARE;
    IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM omnixat_csv_requests.worker_request(organisation,evidence,job,selected_cells) r
      WHERE (r.policy_version,r.content_sha256)=(expected_policy,expected_digest)) THEN
        RETURN QUERY SELECT 'ineligible'::text,NULL::timestamptz; RETURN;
    END IF;
    IF jsonb_typeof(result_amounts) IS DISTINCT FROM 'array' THEN
        RETURN QUERY SELECT 'ineligible'::text,NULL::timestamptz; RETURN;
    END IF;
    IF (SELECT jsonb_agg(jsonb_build_object('field_name',v->'field_name','row',v->'row','column',v->'column') ORDER BY n)
        FROM jsonb_array_elements(result_amounts) WITH ORDINALITY AS x(v,n)) IS DISTINCT FROM selected_cells THEN
        RETURN QUERY SELECT 'ineligible'::text,NULL::timestamptz; RETURN;
    END IF;
    RETURN QUERY SELECT * FROM omnixat_extraction.store_csv_result(organisation,evidence,job,expected_policy,expected_digest,result_amounts);
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_requests.store_requested_result(uuid,uuid,uuid,jsonb,text,bytea,jsonb) FROM PUBLIC;

CREATE FUNCTION omnixat_csv_requests.cancel_csv(
    requested_issuer text,requested_subject text,issued_at bigint,
    organisation uuid,evidence uuid,job uuid,expected_actor uuid
) RETURNS TABLE (outcome text,job_id uuid,cancelled_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE actor uuid; request omnixat.csv_extraction_requests%ROWTYPE; tenant uuid;
BEGIN
    tenant:=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
        AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor');
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR actor<>expected_actor THEN RAISE no_data_found; END IF;
    SELECT r.* INTO request FROM omnixat.csv_extraction_requests r
      WHERE r.tenant_id=tenant AND r.organisation_id=organisation AND r.evidence_id=evidence AND r.job_id=job FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    IF request.cancelled_at IS NOT NULL THEN
        RETURN QUERY SELECT 'cancelled'::text,request.job_id,request.cancelled_at; RETURN;
    END IF;
    -- A separate statement after the lock observes a competing committed result.
    IF EXISTS (SELECT 1 FROM omnixat.csv_extraction_results r WHERE r.tenant_id=tenant AND r.job_id=job) THEN
        RETURN QUERY SELECT 'result_recorded'::text,request.job_id,NULL::timestamptz; RETURN;
    END IF;
    UPDATE omnixat.csv_extraction_requests r SET cancelled_at=clock_timestamp(),cancelled_by=actor
      WHERE r.tenant_id=tenant AND r.job_id=job
      RETURNING r.* INTO request;
    RETURN QUERY SELECT 'cancelled'::text,request.job_id,request.cancelled_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_requests.cancel_csv(text,text,bigint,uuid,uuid,uuid,uuid) FROM PUBLIC;

CREATE SCHEMA omnixat_csv_request_status;
REVOKE ALL ON SCHEMA omnixat_csv_request_status FROM PUBLIC;
CREATE FUNCTION omnixat_csv_request_status.read_requests(
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
        CASE WHEN r.cancelled_at IS NOT NULL THEN 'cancelled'
             WHEN x.job_id IS NOT NULL THEN 'result_recorded' ELSE 'awaiting_worker' END
      FROM omnixat.csv_extraction_requests r
      JOIN omnixat.evidence_registrations e ON (e.tenant_id,e.id,e.organisation_id)=(r.tenant_id,r.evidence_id,r.organisation_id)
      LEFT JOIN omnixat.csv_extraction_results x ON (x.tenant_id,x.job_id)=(r.tenant_id,r.job_id)
      WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND r.organisation_id=organisation AND r.evidence_id=evidence AND (job IS NULL OR r.job_id=job)
      ORDER BY r.requested_at DESC,r.job_id DESC LIMIT 21;
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_request_status.read_requests(text,text,bigint,uuid,uuid,uuid) FROM PUBLIC;
