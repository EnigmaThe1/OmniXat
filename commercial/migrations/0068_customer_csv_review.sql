CREATE SCHEMA omnixat_customer_review;
REVOKE ALL ON SCHEMA omnixat_customer_review FROM PUBLIC;
CREATE INDEX csv_result_evidence_latest ON omnixat.csv_extraction_results
    (tenant_id,evidence_id,stored_at DESC,job_id DESC);

-- No original or extraction/write/approval capability is granted to the web login.
CREATE FUNCTION omnixat_customer_review.read_latest_csv(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid
) RETURNS TABLE (job_id uuid,policy_version text,extractor_version text,content_sha256 bytea,
                 amounts jsonb,stored_at timestamptz,answers jsonb)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),
            set_config('omnixat.subject',requested_subject,true);
    RETURN QUERY SELECT r.job_id,v.policy_version,v.extractor_version,v.content_sha256,
                        v.amounts,v.stored_at,v.answers
    FROM omnixat.csv_extraction_results r
    CROSS JOIN LATERAL omnixat_extraction.read_csv_review_with_answers(organisation,evidence,r.job_id) v
    WHERE r.tenant_id=NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid
      AND r.evidence_id=evidence AND v.extractor_version='csv-amount-v1'
      AND EXISTS (SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
        WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
          AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
          AND m.tenant_id=r.tenant_id AND m.revoked_at IS NULL)
    ORDER BY r.stored_at DESC,r.job_id DESC LIMIT 1;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_review.read_latest_csv(text,text,bigint,uuid,uuid) FROM PUBLIC;
