"""Internal PostgreSQL staff sessions. Browser transport is deliberately separate."""
from contextlib import contextmanager
from hashlib import sha256
import re
from secrets import token_urlsafe
from uuid import UUID

from psycopg.rows import dict_row

from .access import Principal
from .identity import AuthenticationError
from .postgres import _idle
from .staff_identity import STAFF_MFA_MAX_AGE_SECONDS, StaffIDTokenVerifier, VerifiedStaffLogin
from .staff_identity_postgres import _current_staff


def _digest(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise AuthenticationError("Staff session rejected")
    return sha256(token.encode("ascii")).digest()


@contextmanager
def _session_cursor(connection, *, read_only=False):
    _idle(connection)
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        if read_only:
            cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        cursor.execute("SET LOCAL lock_timeout = '1s'")
        cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
        cursor.execute("""
            SELECT current_user <> session_user OR r.rolsuper OR r.rolbypassrls
                OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
                OR EXISTS (SELECT FROM pg_auth_members m WHERE m.member = r.oid)
                OR pg_has_role(current_user, 'pg_database_owner', 'MEMBER')
                OR pg_has_role(current_user, c.relowner, 'MEMBER')
                OR pg_has_role(current_user, n.nspowner, 'MEMBER')
                OR has_schema_privilege(n.oid, 'CREATE')
                OR NOT has_schema_privilege(n.oid, 'USAGE')
                OR NOT has_table_privilege(c.oid, 'SELECT')
                OR NOT has_table_privilege(c.oid, 'INSERT')
                OR NOT has_table_privilege(c.oid, 'DELETE')
                OR has_any_column_privilege(c.oid, 'UPDATE, REFERENCES')
                OR has_table_privilege(c.oid, 'TRUNCATE, TRIGGER')
                OR EXISTS (
                    SELECT FROM pg_namespace s
                    WHERE s.nspname IN ('omnixat', 'omnixat_staff', 'omnixat_staff_login',
                                        'omnixat_billing', 'omnixat_sandbox', 'omnixat_metrics')
                      AND has_schema_privilege(s.oid, 'USAGE, CREATE')
                ) AS unsafe
            FROM pg_roles r CROSS JOIN pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE r.rolname = current_user AND n.nspname = 'omnixat_staff_session'
              AND c.relname = 'sessions' AND c.relkind = 'r'
        """)
        safety = cursor.fetchone()
        if safety is None or safety["unsafe"]:
            raise PermissionError("Dedicated staff session login required")
        yield cursor


def issue_staff_session(sessions, directory, verifier: StaffIDTokenVerifier, id_token, *, expected_nonce) -> str:
    """Issue only after the trusted callback consumes its login transaction and exchanges its code."""
    identity = verifier.verify(id_token, expected_nonce=expected_nonce)
    actor = _current_staff(directory, identity)
    token = token_urlsafe(32)
    with _session_cursor(sessions) as cursor:
        cursor.execute("""
            INSERT INTO omnixat_staff_session.sessions
                (token_digest, membership_id, issuer, subject, authenticated_at, expires_at)
            SELECT %s, %s, %s, %s, %s, expiry
            FROM (SELECT to_timestamp(%s) + %s * interval '1 second' AS expiry) AS times
            WHERE expiry > clock_timestamp()
        """, (_digest(token), UUID(actor.user_id), identity.issuer, identity.subject,
              identity.authenticated_at, identity.authenticated_at, STAFF_MFA_MAX_AGE_SECONDS))
        if cursor.rowcount != 1:
            raise AuthenticationError("Staff session rejected")
    return token


def resolve_staff_session(sessions, directory, token) -> Principal:
    """Resolve authority afresh for one internal request; never cache the principal."""
    digest = _digest(token)
    with _session_cursor(sessions, read_only=True) as cursor:
        cursor.execute("""
            SELECT membership_id, issuer, subject, authenticated_at
            FROM omnixat_staff_session.sessions
            WHERE token_digest = %s AND expires_at > clock_timestamp()
        """, (digest,))
        row = cursor.fetchone()
    if row is None:
        raise AuthenticationError("Staff session rejected")
    actor = _current_staff(directory, VerifiedStaffLogin(row["issuer"], row["subject"], row["authenticated_at"]))
    if UUID(actor.user_id) != row["membership_id"]:
        raise AuthenticationError("Staff session rejected")
    return actor


def revoke_staff_session(sessions, token) -> None:
    """Invalidate an opaque session; repeating a successful logout is harmless."""
    digest = _digest(token)
    with _session_cursor(sessions) as cursor:
        cursor.execute("DELETE FROM omnixat_staff_session.sessions WHERE token_digest = %s", (digest,))
