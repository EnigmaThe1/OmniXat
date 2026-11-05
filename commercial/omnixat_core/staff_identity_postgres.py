"""Resolve a verified staff login through the current separate staff directory."""
from psycopg.rows import dict_row

from .access import Principal
from .identity import AuthenticationError
from .postgres import _idle
from .staff_identity import StaffIDTokenVerifier


def resolve_staff_login(connection, verifier: StaffIDTokenVerifier, token, *, expected_nonce) -> Principal:
    """Internal callback boundary; never accept an ID token as an API bearer."""
    identity = verifier.verify(token, expected_nonce=expected_nonce)
    _idle(connection)
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
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
                OR has_any_column_privilege(c.oid, 'INSERT, UPDATE, REFERENCES')
                OR has_table_privilege(c.oid, 'DELETE, TRUNCATE, TRIGGER')
                OR NOT row_security_active(c.oid)
                OR EXISTS (
                    SELECT FROM pg_namespace s
                    WHERE s.nspname IN ('omnixat', 'omnixat_billing', 'omnixat_sandbox', 'omnixat_metrics')
                      AND has_schema_privilege(s.oid, 'USAGE, CREATE')
                ) AS unsafe
            FROM pg_roles r CROSS JOIN pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE r.rolname = current_user AND n.nspname = 'omnixat_staff'
              AND c.relname = 'memberships' AND c.relkind = 'r'
        """)
        safety = cursor.fetchone()
        if safety is None or safety["unsafe"]:
            raise PermissionError("Dedicated staff directory login required")
        cursor.execute("""SELECT set_config('omnixat.staff_issuer', %s, true),
                                 set_config('omnixat.staff_subject', %s, true)""",
                       (identity.issuer, identity.subject))
        cursor.execute("""SELECT id, role FROM omnixat_staff.memberships
            WHERE issuer = %s AND subject = %s AND revoked_at IS NULL
              AND auth_valid_after < %s
              AND statement_timestamp() < to_timestamp(%s) + interval '300 seconds'
        """, (identity.issuer, identity.subject, identity.authenticated_at, identity.authenticated_at))
        member = cursor.fetchone()
        if member is None:
            raise AuthenticationError("Staff authentication denied")
        return Principal(str(member["id"]), None, staff_role=member["role"], mfa_verified=True)
