CREATE TABLE omnixat.csv_extraction_requests (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    organisation_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    selections jsonb NOT NULL CHECK (CASE WHEN jsonb_typeof(selections)='array'
        THEN jsonb_array_length(selections) BETWEEN 1 AND 32 AND octet_length(selections::text)<=8192 ELSE false END),
    policy_version text NOT NULL,
    content_sha256 bytea NOT NULL,
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 524288),
    requested_by uuid NOT NULL REFERENCES omnixat.identities(id),
    requested_issuer text NOT NULL,
    requested_subject text NOT NULL,
    authorised_iat bigint NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,job_id),
    FOREIGN KEY (tenant_id,organisation_id) REFERENCES omnixat.organisations(tenant_id,id),
    FOREIGN KEY (tenant_id,evidence_id,content_sha256,byte_size)
      REFERENCES omnixat.evidence_quarantine(tenant_id,evidence_id,content_sha256,byte_size)
);
ALTER TABLE omnixat.csv_extraction_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.csv_extraction_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON omnixat.csv_extraction_requests
    USING (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid)
    WITH CHECK (tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid);
REVOKE ALL ON omnixat.csv_extraction_requests FROM PUBLIC;
CREATE SCHEMA omnixat_csv_requests;
REVOKE ALL ON SCHEMA omnixat_csv_requests FROM PUBLIC;

CREATE FUNCTION omnixat_csv_requests.request_csv(
    requested_issuer text,requested_subject text,issued_at bigint,organisation uuid,evidence uuid,
    job uuid,expected_actor uuid,selected_cells jsonb
) RETURNS TABLE (job_id uuid,policy_version text,requested_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE actor uuid; tenant uuid; source record; previous omnixat.csv_extraction_requests%ROWTYPE;
BEGIN
    tenant:=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
    PERFORM set_config('omnixat.issuer',requested_issuer,true),set_config('omnixat.subject',requested_subject,true);
    SELECT i.id INTO actor FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
      WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
        AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
        AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor');
    IF actor IS NULL THEN RAISE insufficient_privilege; END IF;
    IF expected_actor IS NULL OR expected_actor<>actor THEN RAISE no_data_found; END IF;
    IF job IS NULL OR selected_cells IS NULL OR jsonb_typeof(selected_cells)<>'array' THEN RAISE invalid_parameter_value; END IF;
    IF jsonb_array_length(selected_cells) NOT BETWEEN 1 AND 32 OR octet_length(selected_cells::text)>8192 THEN RAISE invalid_parameter_value; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(selected_cells) v WHERE
      jsonb_typeof(v)<>'object' OR NOT (v ?& ARRAY['field_name','row','column'])
      OR v-ARRAY['field_name','row','column']<>'{}'::jsonb
      OR jsonb_typeof(v->'field_name') IS DISTINCT FROM 'string'
      OR (v->>'field_name') COLLATE "C" !~ '^[a-z][a-z0-9_]{0,63}$'
      OR jsonb_typeof(v->'row') IS DISTINCT FROM 'number' OR (v->>'row') !~ '^[0-9]{1,4}$'
      OR jsonb_typeof(v->'column') IS DISTINCT FROM 'number' OR (v->>'column') !~ '^[0-9]{1,2}$') THEN RAISE invalid_parameter_value; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(selected_cells) v
      WHERE (v->>'row')::integer NOT BETWEEN 1 AND 5000 OR (v->>'column')::integer NOT BETWEEN 1 AND 64)
      OR (SELECT count(DISTINCT v->>'field_name') FROM jsonb_array_elements(selected_cells) v)<>jsonb_array_length(selected_cells)
      THEN RAISE invalid_parameter_value; END IF;
    -- Pin the operator policy for insertion. No original bytes leave this function.
    PERFORM 1 FROM omnixat_extraction.active_scan_policy p FOR SHARE;
    SELECT a.policy_version,a.content_sha256,a.byte_size INTO source
      FROM omnixat_extraction.read_eligible_original(organisation,evidence) a
      WHERE a.media_type='text/csv' AND a.byte_size BETWEEN 1 AND 524288;
    IF NOT FOUND THEN RETURN; END IF;
    IF NOT EXISTS (SELECT 1 FROM omnixat.csv_extraction_requests r WHERE r.tenant_id=tenant AND r.job_id=job)
      AND EXISTS (SELECT 1 FROM omnixat.csv_extraction_results r WHERE r.tenant_id=tenant AND r.job_id=job)
      THEN RAISE unique_violation; END IF;
    INSERT INTO omnixat.csv_extraction_requests AS existing
      (tenant_id,job_id,organisation_id,evidence_id,selections,policy_version,content_sha256,byte_size,
       requested_by,requested_issuer,requested_subject,authorised_iat)
      VALUES (tenant,job,organisation,evidence,selected_cells,source.policy_version,source.content_sha256,source.byte_size,
              actor,requested_issuer,requested_subject,issued_at) ON CONFLICT DO NOTHING;
    SELECT r.* INTO STRICT previous FROM omnixat.csv_extraction_requests r WHERE r.tenant_id=tenant AND r.job_id=job;
    IF (previous.organisation_id,previous.evidence_id,previous.selections,previous.requested_by,previous.policy_version,previous.content_sha256)
       IS DISTINCT FROM (organisation,evidence,selected_cells,actor,source.policy_version,source.content_sha256)
       THEN RAISE unique_violation; END IF;
    RETURN QUERY SELECT previous.job_id,previous.policy_version,previous.requested_at;
END $$;
REVOKE ALL ON FUNCTION omnixat_csv_requests.request_csv(text,text,bigint,uuid,uuid,uuid,uuid,jsonb) FROM PUBLIC;

CREATE FUNCTION omnixat_csv_requests.worker_request(organisation uuid,evidence uuid,job uuid,selected_cells jsonb)
RETURNS TABLE (policy_version text,content_sha256 bytea)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ DECLARE request omnixat.csv_extraction_requests%ROWTYPE;
BEGIN
    SELECT r.* INTO request FROM omnixat.csv_extraction_requests r
      WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
        AND r.job_id=job AND r.organisation_id=organisation AND r.evidence_id=evidence AND r.selections=selected_cells;
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

CREATE FUNCTION omnixat_csv_requests.store_requested_result(
    organisation uuid,evidence uuid,job uuid,selected_cells jsonb,
    expected_policy text,expected_digest bytea,result_amounts jsonb
) RETURNS TABLE (outcome text,stored_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ BEGIN
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
