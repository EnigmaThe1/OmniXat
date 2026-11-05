"""Internal one-time OIDC login transactions; no HTTP or provider calls."""
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re
from secrets import token_urlsafe
from urllib.parse import urlsplit

from .identity import AuthenticationError
from .postgres import _idle


@dataclass(frozen=True, repr=False)
class LoginStart:
    state: str
    nonce: str
    code_challenge: str


@dataclass(frozen=True, repr=False)
class ConsumedLogin:
    nonce: str
    code_verifier: str


def _urlsafe(data):
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _opaque(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None


def _https_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    if any(ord(c) <= 32 or ord(c) >= 127 or c in "\\?#" for c in value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None


def _check_connection(connection):
    connection.execute("SET LOCAL statement_timeout = '5s'")
    connection.execute("SET LOCAL lock_timeout = '1s'")
    connection.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
    result = connection.execute("""
        SELECT current_user <> session_user OR r.rolsuper OR r.rolbypassrls
            OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
            OR EXISTS (SELECT FROM pg_auth_members m WHERE m.member = r.oid)
            OR pg_has_role(current_user, 'pg_database_owner', 'MEMBER')
            OR pg_has_role(current_user, c.relowner, 'MEMBER')
            OR pg_has_role(current_user, n.nspowner, 'MEMBER')
            OR has_schema_privilege(n.oid, 'CREATE')
            OR NOT has_schema_privilege(n.oid, 'USAGE')
            OR NOT has_table_privilege(c.oid, 'SELECT')
            OR NOT has_table_privilege(c.oid, 'DELETE')
            OR NOT has_column_privilege(c.oid, 'state_key', 'INSERT')
            OR NOT has_column_privilege(c.oid, 'browser_key', 'INSERT')
            OR has_column_privilege(c.oid, 'expires_at', 'INSERT')
            OR has_any_column_privilege(c.oid, 'UPDATE, REFERENCES')
            OR has_table_privilege(c.oid, 'TRUNCATE, TRIGGER')
            OR EXISTS (
                SELECT FROM pg_namespace s
                WHERE s.nspname IN ('omnixat', 'omnixat_staff', 'omnixat_billing', 'omnixat_sandbox', 'omnixat_metrics')
                  AND has_schema_privilege(s.oid, 'USAGE, CREATE')
            ) AS unsafe
        FROM pg_roles r CROSS JOIN pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE r.rolname = current_user AND n.nspname = 'omnixat_staff_login'
          AND c.relname = 'transactions' AND c.relkind = 'r'
    """).fetchone()
    if result is None or result[0]:
        raise PermissionError("Dedicated staff login transaction role required")


class PostgresStaffLoginTransactions:
    """Use a trusted configuration and an exclusive idle autocommit connection per call."""

    def __init__(self, *, issuer, client_id, redirect_uri, key):
        if not _https_url(issuer) or not _https_url(redirect_uri):
            raise ValueError("Pinned HTTPS issuer and redirect URI required")
        if not isinstance(client_id, str) or not 1 <= len(client_id) <= 255 or not client_id.strip():
            raise ValueError("Pinned staff client required")
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("A dedicated 32-byte server key is required")
        self._key = key
        self._profile = json.dumps([issuer, client_id, redirect_uri], separators=(",", ":")).encode("ascii")

    def _derive(self, purpose, *values):
        return hmac.digest(self._key, b"omnixat.staff-login.v1\x00" + purpose + b"\x00"
                           + self._profile + b"\x00" + b"\x00".join(v.encode("ascii") for v in values),
                           "sha256")

    def _material(self, state, browser_binding):
        nonce = self._derive(b"nonce", state, browser_binding).hex()
        verifier = _urlsafe(self._derive(b"pkce", state, browser_binding))
        return ConsumedLogin(nonce, verifier)

    def begin(self, connection, *, browser_binding):
        if not _opaque(browser_binding):
            raise ValueError("Server-generated browser binding required")
        state = token_urlsafe(32)
        with _login_transaction(connection):
            connection.execute("""
                INSERT INTO omnixat_staff_login.transactions (state_key, browser_key) VALUES (%s, %s)
            """, (self._derive(b"state", state), self._derive(b"browser", state, browser_binding)))
        material = self._material(state, browser_binding)
        return LoginStart(state, material.nonce, _urlsafe(sha256(material.code_verifier.encode("ascii")).digest()))

    def consume(self, connection, *, state, browser_binding):
        if not _opaque(state) or not _opaque(browser_binding):
            raise AuthenticationError("Staff login transaction rejected")
        with _login_transaction(connection):
            row = connection.execute("""
                DELETE FROM omnixat_staff_login.transactions
                WHERE state_key = %s AND browser_key = %s
                RETURNING expires_at > clock_timestamp()
            """, (self._derive(b"state", state), self._derive(b"browser", state, browser_binding))).fetchone()
        if row is None or not row[0]:
            raise AuthenticationError("Staff login transaction rejected")
        return self._material(state, browser_binding)


@contextmanager
def _login_transaction(connection):
    _idle(connection)
    with connection.transaction():
        _check_connection(connection)
        yield
