"""One-shot operator command for bounded staff authentication cleanup."""
import argparse
from dataclasses import asdict, dataclass
import json
import os
import sys

import psycopg
from psycopg.rows import tuple_row

from .postgres import _idle

_DSN_ENV = "OMNIXAT_STAFF_MAINTENANCE_DSN"


@dataclass(frozen=True)
class CleanupResult:
    batches: int
    login_attempts_deleted: int
    staff_sessions_deleted: int


def _limits(batch_size, max_batches):
    if type(batch_size) is not int or not 1 <= batch_size <= 500:
        raise ValueError("Batch size must be from 1 to 500")
    if type(max_batches) is not int or not 1 <= max_batches <= 10:
        raise ValueError("Maximum batches must be from 1 to 10")


def prune_staff_auth(connection, *, batch_size=100, max_batches=4):
    """Commit up to max_batches calls; leave locked or excess work for later."""
    _limits(batch_size, max_batches)
    _idle(connection)
    attempts = sessions = 0
    for batch in range(1, max_batches + 1):
        with connection.transaction(), connection.cursor(row_factory=tuple_row) as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SET LOCAL search_path = pg_catalog, pg_temp")
            cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
            if batch == 1:
                cursor.execute("""
                    SELECT current_user <> session_user OR r.rolsuper OR r.rolbypassrls
                        OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
                        OR EXISTS (SELECT FROM pg_auth_members m WHERE m.member = r.oid)
                        OR pg_has_role(current_user, 'pg_database_owner', 'MEMBER')
                        OR pg_has_role(current_user, p.proowner, 'MEMBER')
                        OR pg_has_role(current_user, n.nspowner, 'MEMBER')
                        OR has_schema_privilege(n.oid, 'CREATE')
                        OR NOT has_schema_privilege(n.oid, 'USAGE')
                        OR NOT has_function_privilege(p.oid, 'EXECUTE')
                        OR EXISTS (
                            SELECT FROM pg_namespace s
                            WHERE s.nspname IN ('omnixat', 'omnixat_staff', 'omnixat_staff_login',
                                                'omnixat_staff_session', 'omnixat_staff_admission',
                                                'omnixat_billing', 'omnixat_sandbox', 'omnixat_metrics')
                              AND has_schema_privilege(s.oid, 'USAGE, CREATE')
                        ) AS unsafe
                    FROM pg_roles r CROSS JOIN pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE r.rolname = current_user
                      AND n.nspname = 'omnixat_staff_maintenance' AND p.proname = 'prune_expired'
                      AND p.prokind = 'f' AND p.pronargs = 1 AND p.proargtypes[0] = 'pg_catalog.int4'::regtype
                """)
                role = cursor.fetchone()
                if role is None or role[0]:
                    raise PermissionError("Dedicated staff maintenance login required")
            cursor.execute("SELECT * FROM omnixat_staff_maintenance.prune_expired(%s)", (batch_size,))
            removed_attempts, removed_sessions = cursor.fetchone()
        attempts += removed_attempts
        sessions += removed_sessions
        if removed_attempts < batch_size and removed_sessions < batch_size:
            break
    return CleanupResult(batch, attempts, sessions)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-batches", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        _limits(args.batch_size, args.max_batches)
    except ValueError as exc:
        parser.error(str(exc))
    dsn = os.environ.get(_DSN_ENV, "")
    if not dsn.strip():
        print(f"Set {_DSN_ENV} for the dedicated maintenance login.", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(dsn, connect_timeout=3, autocommit=True) as connection:
            result = prune_staff_auth(connection, batch_size=args.batch_size, max_batches=args.max_batches)
    except (psycopg.Error, ValueError, PermissionError):
        print("Staff authentication cleanup failed; committed batches may already have completed.", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
