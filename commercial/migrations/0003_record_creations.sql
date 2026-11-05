-- A creation receipt reserves one result and is also a minimal audit event.
-- Deferred FKs prevent a reservation from committing without its result.
CREATE TABLE omnixat.record_creations (
    tenant_id uuid NOT NULL REFERENCES omnixat.tenants(id),
    actor_id text NOT NULL CHECK (length(actor_id) BETWEEN 1 AND 200),
    operation text NOT NULL,
    key_digest bytea,
    payload_digest bytea,
    organisation_id uuid,
    note_id uuid,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK ((key_digest IS NULL AND payload_digest IS NULL) OR
           (key_digest IS NOT NULL AND payload_digest IS NOT NULL AND
            octet_length(key_digest) = 32 AND octet_length(payload_digest) = 32)),
    CHECK ((operation = 'organisation.create' AND organisation_id IS NOT NULL AND note_id IS NULL) OR
           (operation = 'note.create' AND note_id IS NOT NULL AND organisation_id IS NULL)),
    UNIQUE (tenant_id, actor_id, operation, key_digest),
    UNIQUE (tenant_id, organisation_id),
    UNIQUE (tenant_id, note_id),
    FOREIGN KEY (tenant_id, organisation_id) REFERENCES omnixat.organisations(tenant_id, id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (tenant_id, note_id) REFERENCES omnixat.notes(tenant_id, id)
        DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE omnixat.record_creations ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.record_creations FORCE ROW LEVEL SECURITY;
CREATE POLICY creation_actor_scope ON omnixat.record_creations
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
           AND actor_id = current_setting('omnixat.record_actor', true))
    WITH CHECK (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
                AND actor_id = current_setting('omnixat.record_actor', true));
REVOKE ALL ON omnixat.record_creations FROM PUBLIC;
-- Runtime requires SELECT and INSERT only; no receipt mutation or deletion.
