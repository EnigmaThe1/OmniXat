CREATE SCHEMA omnixat_staff;
REVOKE ALL ON SCHEMA omnixat_staff FROM PUBLIC;

CREATE TABLE omnixat_staff.memberships (
    id uuid PRIMARY KEY,
    issuer text NOT NULL CHECK (length(issuer) BETWEEN 1 AND 2048),
    subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    role text NOT NULL CHECK (role IN ('platform_owner', 'supervisor', 'billing_admin', 'support')),
    revoked_at timestamptz,
    auth_valid_after bigint NOT NULL DEFAULT 0 CHECK (auth_valid_after >= 0),
    UNIQUE (issuer, subject)
);

ALTER TABLE omnixat_staff.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE omnixat_staff.memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY staff_membership_lookup ON omnixat_staff.memberships FOR SELECT
    USING (issuer = current_setting('omnixat.staff_issuer', true)
           AND subject = current_setting('omnixat.staff_subject', true));
REVOKE ALL ON omnixat_staff.memberships FROM PUBLIC;
