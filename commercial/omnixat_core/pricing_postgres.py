"""Internal staff catalogue. Use verified principals and a dedicated DB login.

No customer transport, subscription state transitions or payment side effects.
"""
from contextlib import contextmanager
from datetime import datetime
import re
from uuid import UUID

from psycopg.rows import dict_row

from .access import require_staff
from .postgres import _idle
from .pricing import PriceVersion, new_price_version

_COLUMNS = "id, plan, amount_minor, currency, interval, trial_days, api_allowance, effective_at"


def _plan_code(code):
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", code):
        raise ValueError("Invalid plan code")
    return code


def _price(row):
    if row is None:
        raise KeyError("Price version not found")
    row["id"] = str(row["id"])
    return PriceVersion(**row)


@contextmanager
def _catalogue_transaction(connection, actor, permission, *, write=False):
    require_staff(actor, permission)
    if actor.tenant_id is not None or actor.tenant_role is not None:
        raise PermissionError("Separate staff principal required")
    if not isinstance(actor.user_id, str) or not 1 <= len(actor.user_id) <= 200 or "\x00" in actor.user_id:
        raise ValueError("Invalid staff identity")
    _idle(connection)
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        if not write:
            cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("""SELECT set_config('statement_timeout', '5000', true),
                                 set_config('lock_timeout', '1000', true),
                                 set_config('idle_in_transaction_session_timeout', '5000', true)""")
        cursor.execute("""SELECT (current_user <> session_user OR rolsuper OR rolbypassrls OR
                   has_schema_privilege('omnixat', 'USAGE') OR
                   has_schema_privilege('omnixat_billing', 'CREATE')) AS unsafe
            FROM pg_roles WHERE rolname = current_user""")
        if cursor.fetchone()["unsafe"]:
            raise PermissionError("Dedicated pricing runtime required")
        cursor.execute("""SELECT count(*) AS total, count(*) FILTER (WHERE
                    pg_has_role(current_user, c.relowner, 'MEMBER') OR
                    pg_has_role(current_user, n.nspowner, 'MEMBER') OR
                    has_any_column_privilege(c.oid, 'UPDATE') OR
                    has_table_privilege(c.oid, 'DELETE, TRUNCATE')) AS unsafe
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='omnixat_billing' AND c.relname IN ('plans','price_versions')""")
        roles = cursor.fetchone()
        if roles["total"] != 2 or roles["unsafe"]:
            raise PermissionError("Append-only pricing grants required")
        yield cursor


class PostgresPriceCatalogue:
    """Each call owns one transaction on the supplied idle autocommit connection."""

    def __init__(self, connection):
        self._connection = connection

    def register_plan(self, actor, *, code, display_name):
        with _catalogue_transaction(self._connection, actor, "prices:write", write=True) as cursor:
            code = _plan_code(code)
            if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 80 or "\x00" in display_name:
                raise ValueError("Plan name required")
            cursor.execute("""INSERT INTO omnixat_billing.plans (code, display_name, created_by)
                VALUES (%s,%s,%s) RETURNING code, display_name""", (code, display_name.strip(), actor.user_id))
            return cursor.fetchone()

    def create(self, actor, *, plan, amount_minor, interval, trial_days, api_allowance, effective_at):
        with _catalogue_transaction(self._connection, actor, "prices:write", write=True) as cursor:
            version = new_price_version(plan=_plan_code(plan), amount_minor=amount_minor, interval=interval,
                                        trial_days=trial_days, api_allowance=api_allowance,
                                        effective_at=effective_at)
            cursor.execute("""INSERT INTO omnixat_billing.price_versions
                (id, plan, amount_minor, currency, interval, trial_days, api_allowance, effective_at, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING """ + _COLUMNS,
                (UUID(version.id), version.plan, version.amount_minor, version.currency, version.interval,
                 version.trial_days, version.api_allowance, version.effective_at, actor.user_id))
            return _price(cursor.fetchone())

    def get(self, actor, version_id):
        with _catalogue_transaction(self._connection, actor, "prices:read") as cursor:
            cursor.execute("SELECT " + _COLUMNS + " FROM omnixat_billing.price_versions WHERE id=%s",
                           (UUID(str(version_id)),))
            return _price(cursor.fetchone())

    def effective(self, actor, *, plan, interval, as_of):
        with _catalogue_transaction(self._connection, actor, "prices:read") as cursor:
            if interval not in ("month", "year") or not isinstance(as_of, datetime) or as_of.utcoffset() is None:
                raise ValueError("Interval and timezone-aware lookup date required")
            cursor.execute("SELECT " + _COLUMNS + """ FROM omnixat_billing.price_versions
                WHERE plan=%s AND interval=%s AND effective_at <= %s
                ORDER BY effective_at DESC LIMIT 1""", (_plan_code(plan), interval, as_of))
            return _price(cursor.fetchone())

    def audit(self, actor, *, plan, limit=50):
        with _catalogue_transaction(self._connection, actor, "prices:audit") as cursor:
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("Audit limit must be between 1 and 100")
            cursor.execute("""SELECT operation, result_id, created_by, created_at FROM (
                SELECT 'plan_registered' AS operation, code AS result_id, created_by, created_at
                FROM omnixat_billing.plans WHERE code=%s
                UNION ALL
                SELECT 'price_version_created', id::text, created_by, created_at FROM (
                    SELECT id, created_by, created_at FROM omnixat_billing.price_versions
                    WHERE plan=%s ORDER BY created_at DESC, id DESC LIMIT %s
                ) versions
            ) events ORDER BY created_at DESC, result_id DESC LIMIT %s""",
                           (_plan_code(plan), plan, limit, limit))
            return tuple(cursor.fetchall())
