CREATE SCHEMA omnixat_staff_session;
REVOKE ALL ON SCHEMA omnixat_staff_session FROM PUBLIC;

CREATE TABLE omnixat_staff_session.sessions (
    token_digest bytea PRIMARY KEY CHECK (octet_length(token_digest) = 32),
    membership_id uuid NOT NULL REFERENCES omnixat_staff.memberships(id) ON DELETE CASCADE,
    issuer text NOT NULL CHECK (length(issuer) BETWEEN 1 AND 2048),
    subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    authenticated_at bigint NOT NULL CHECK (authenticated_at > 0),
    expires_at timestamptz NOT NULL CHECK (isfinite(expires_at))
);
CREATE INDEX staff_sessions_membership ON omnixat_staff_session.sessions (membership_id);
CREATE INDEX staff_sessions_expiry ON omnixat_staff_session.sessions (expires_at);
REVOKE ALL ON omnixat_staff_session.sessions FROM PUBLIC;
