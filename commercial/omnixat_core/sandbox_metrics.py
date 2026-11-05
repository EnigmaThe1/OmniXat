"""Owner-only, aggregate snapshot of local billing simulation."""
from dataclasses import dataclass
from datetime import datetime

from psycopg.rows import dict_row

from .access import Principal, require_staff
from .postgres import _idle


@dataclass(frozen=True)
class SandboxMetrics:
    observed_at: datetime
    pending: int
    trialing: int
    trial_expired: int
    cancelled: int
    matched: int
    price_mismatch: int
    state_mismatch: int


def read_sandbox_metrics(connection, actor: Principal) -> SandboxMetrics:
    """Read current counts using a dedicated idle autocommit connection."""
    require_staff(actor, "sandbox-metrics:read")
    if actor.tenant_id is not None or actor.tenant_role is not None:
        raise PermissionError("Separate staff principal required")
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
                OR EXISTS (
                    SELECT FROM pg_namespace source
                    WHERE source.nspname IN ('omnixat', 'omnixat_billing', 'omnixat_sandbox')
                      AND has_schema_privilege(source.oid, 'USAGE, CREATE')
                ) AS unsafe
            FROM pg_roles r
            CROSS JOIN pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE r.rolname = current_user AND n.nspname = 'omnixat_metrics'
              AND c.relname = 'sandbox_snapshot' AND c.relkind = 'v'
        """)
        grant_check = cursor.fetchone()
        if grant_check is None or grant_check["unsafe"]:
            raise PermissionError("Dedicated sandbox metrics runtime required")
        cursor.execute("""
            SELECT observed_at, pending, trialing, trial_expired, cancelled,
                   matched, price_mismatch, state_mismatch
            FROM omnixat_metrics.sandbox_snapshot
        """)
        return SandboxMetrics(**cursor.fetchone())
