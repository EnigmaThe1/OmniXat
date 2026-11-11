CREATE SCHEMA omnixat_customer_drafts;
REVOKE ALL ON SCHEMA omnixat_customer_drafts FROM PUBLIC;
CREATE INDEX csv_expense_draft_evidence_latest ON omnixat.csv_expense_drafts
    (tenant_id,organisation_id,evidence_id,created_at DESC,id DESC);

-- Read-only capability. No original, draft mutation, journal or approval grants.
CREATE FUNCTION omnixat_customer_drafts.read_csv_expense_drafts(
    requested_issuer text, requested_subject text, issued_at bigint,
    organisation uuid, evidence uuid, requested_draft uuid
) RETURNS TABLE (
    draft_id uuid, expense_created_at timestamptz, expense_created_by text,
    amount_pence numeric, currency text, accounting_date date, expense_account_id uuid, period_id uuid,
    evidence_id uuid, job_id uuid, field_name text, source_row integer, source_column integer,
    amount text, source_kind text, created_by text, created_at timestamptz,
    policy_version text, content_sha256 bytea
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$
DECLARE tenant uuid := NULLIF(current_setting('omnixat.tenant_id',true),'')::uuid;
BEGIN
    PERFORM set_config('omnixat.issuer',requested_issuer,true),
            set_config('omnixat.subject',requested_subject,true);
    IF NOT EXISTS (
        SELECT 1 FROM omnixat.identities i JOIN omnixat.memberships m ON m.user_id=i.id
        WHERE i.issuer=requested_issuer AND i.subject=requested_subject
          AND i.disabled_at IS NULL AND i.actor_kind='human' AND issued_at>i.tokens_valid_after
          AND m.tenant_id=tenant AND m.revoked_at IS NULL AND m.role IN ('owner','editor','viewer')
    ) THEN RETURN; END IF;
    RETURN QUERY SELECT v.*
    FROM omnixat.csv_expense_drafts d
    CROSS JOIN LATERAL omnixat_extraction.read_csv_expense_draft(organisation,d.id) v
    WHERE d.tenant_id=tenant AND d.organisation_id=organisation AND d.evidence_id=evidence
      AND (requested_draft IS NULL OR d.id=requested_draft)
    ORDER BY d.created_at DESC,d.id DESC LIMIT 21;
END $$;
REVOKE ALL ON FUNCTION omnixat_customer_drafts.read_csv_expense_drafts(text,text,bigint,uuid,uuid,uuid) FROM PUBLIC;
