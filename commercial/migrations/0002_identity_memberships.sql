-- Authoritative identity links are provisioned by a separate trusted service.
-- Never create membership from token role/email/tenant claims.
CREATE TABLE omnixat.identities (
    id uuid PRIMARY KEY,
    issuer text NOT NULL CHECK (length(issuer) BETWEEN 1 AND 2048),
    subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    actor_kind text NOT NULL CHECK (actor_kind IN ('human', 'agent')),
    disabled_at timestamptz,
    tokens_valid_after bigint NOT NULL DEFAULT 0 CHECK (tokens_valid_after >= 0),
    UNIQUE (issuer, subject)
);
CREATE TABLE omnixat.memberships (
    tenant_id uuid NOT NULL REFERENCES omnixat.tenants(id),
    user_id uuid NOT NULL REFERENCES omnixat.identities(id),
    role text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    revoked_at timestamptz,
    PRIMARY KEY (tenant_id, user_id)
);
ALTER TABLE omnixat.identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.identities FORCE ROW LEVEL SECURITY;
ALTER TABLE omnixat.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat.memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY identity_lookup ON omnixat.identities FOR SELECT
    USING (issuer = current_setting('omnixat.issuer', true)
           AND subject = current_setting('omnixat.subject', true));
CREATE POLICY membership_lookup ON omnixat.memberships FOR SELECT
    USING (tenant_id = NULLIF(current_setting('omnixat.tenant_id', true), '')::uuid
           AND user_id IN (SELECT id FROM omnixat.identities));
REVOKE ALL ON omnixat.identities, omnixat.memberships FROM PUBLIC;
-- Runtime gets SELECT only on these tables. Administrative provisioning/revocation
-- uses separately scoped credentials; no runtime membership mutation endpoint.
