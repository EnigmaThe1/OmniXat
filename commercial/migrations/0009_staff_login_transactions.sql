CREATE SCHEMA omnixat_staff_login;
REVOKE ALL ON SCHEMA omnixat_staff_login FROM PUBLIC;

CREATE TABLE omnixat_staff_login.transactions (
    state_key bytea PRIMARY KEY CHECK (octet_length(state_key) = 32),
    browser_key bytea NOT NULL CHECK (octet_length(browser_key) = 32),
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + interval '5 minutes')
        CHECK (isfinite(expires_at))
);

CREATE INDEX staff_login_transactions_expiry ON omnixat_staff_login.transactions (expires_at);
REVOKE ALL ON omnixat_staff_login.transactions FROM PUBLIC;
