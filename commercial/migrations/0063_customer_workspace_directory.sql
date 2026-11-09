-- Directory capability can see only the verified subject's active memberships.
-- Extra cross-tenant policies apply to the migration/function owner only, never
-- the ordinary record runtime. All returned fields are explicitly selected.
CREATE INDEX memberships_user_tenant ON omnixat.memberships(user_id,tenant_id);
CREATE SCHEMA omnixat_directory;
REVOKE ALL ON SCHEMA omnixat_directory FROM PUBLIC;
DO $$ BEGIN
    EXECUTE format('CREATE POLICY directory_memberships ON omnixat.memberships FOR SELECT TO %I
        USING (current_setting(''omnixat.directory_mode'',true) = ''on''
               AND user_id IN (SELECT id FROM omnixat.identities))', current_user);
    EXECUTE format('CREATE POLICY directory_tenants ON omnixat.tenants FOR SELECT TO %I
        USING (current_setting(''omnixat.directory_mode'',true) = ''on''
               AND id IN (SELECT tenant_id FROM omnixat.memberships))', current_user);
END $$;
CREATE FUNCTION omnixat_directory.list_workspaces(
    requested_issuer text, requested_subject text, issued_at bigint, after_id uuid, page_size integer
) RETURNS TABLE (id uuid, display_name text, role text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $$ BEGIN
    IF page_size NOT BETWEEN 1 AND 51 OR page_size IS NULL THEN
        RAISE EXCEPTION 'Invalid directory page' USING ERRCODE='22023';
    END IF;
    PERFORM set_config('omnixat.directory_mode','on',true),
            set_config('omnixat.issuer',requested_issuer,true), set_config('omnixat.subject',requested_subject,true);
    RETURN QUERY SELECT t.id,t.display_name,m.role FROM omnixat.identities i
        JOIN omnixat.memberships m ON m.user_id=i.id JOIN omnixat.tenants t ON t.id=m.tenant_id
        WHERE i.issuer=requested_issuer AND i.subject=requested_subject AND i.disabled_at IS NULL
            AND issued_at > i.tokens_valid_after AND m.revoked_at IS NULL
            AND (after_id IS NULL OR t.id > after_id)
        ORDER BY t.id LIMIT page_size;
END $$;
REVOKE ALL ON FUNCTION omnixat_directory.list_workspaces(text,text,bigint,uuid,integer) FROM PUBLIC;
