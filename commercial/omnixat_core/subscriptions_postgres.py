"""Internal sandbox only. Nothing here activates, charges or renews a subscription."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from .access import require_tenant
from .postgres import _tenant_transaction
from .pricing_postgres import _plan_code


class SandboxSubscriptionConflict(Exception):
    """An existing sandbox subscription or its state prevents the operation."""


@dataclass(frozen=True)
class SandboxSubscription:
    id: UUID
    tenant_id: UUID
    price_version_id: UUID
    plan: str
    amount_minor: int
    currency: str
    interval: str
    api_allowance: int
    started_at: datetime
    trial_ends_at: datetime | None
    cancelled_at: datetime | None
    state: str


@contextmanager
def _sandbox_transaction(connection, tenant, *, write=False, extra_tables=(), select_only=("price_terms",)):
    with _tenant_transaction(connection, tenant, write=write, schema="omnixat_sandbox",
                             tables_required=("subscriptions", "cancellations") + extra_tables):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""SELECT current_user <> session_user OR
                has_schema_privilege('omnixat', 'USAGE') OR
                has_schema_privilege('omnixat_billing', 'USAGE') OR
                has_schema_privilege('omnixat_sandbox', 'CREATE') OR EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='omnixat_sandbox' AND c.relkind IN ('r','v') AND
                        (pg_has_role(current_user, n.nspowner, 'MEMBER') OR
                         pg_has_role(current_user, c.relowner, 'MEMBER') OR
                         has_any_column_privilege(c.oid, 'UPDATE') OR
                         has_table_privilege(c.oid, 'DELETE, TRUNCATE') OR
                         (c.relname=ANY(%s) AND has_any_column_privilege(c.oid, 'INSERT')))
                ) AS unsafe""", (list(select_only),))
            if cursor.fetchone()["unsafe"]:
                raise PermissionError("Dedicated append-only sandbox login required")
            yield cursor


class PostgresSubscriptionSandbox:
    def __init__(self, connection, *, clock=lambda: datetime.now(timezone.utc)):
        self._connection = connection
        self._clock = clock

    def _now(self):
        at = self._clock()
        if not isinstance(at, datetime) or at.utcoffset() is None:
            raise ValueError("Sandbox clock must provide an aware datetime")
        return at.astimezone(timezone.utc)

    @contextmanager
    def _unit(self, actor, tenant_id, *, write=False):
        require_tenant(actor, tenant_id, "billing:manage")
        if actor.actor_kind != "human" or actor.api_scopes is not None or actor.mfa_verified is not True or actor.staff_role is not None:
            raise PermissionError("Verified interactive tenant owner required")
        if not isinstance(actor.user_id, str) or not 1 <= len(actor.user_id) <= 200 or "\x00" in actor.user_id:
            raise ValueError("Invalid tenant actor")
        tenant = UUID(tenant_id)
        with _sandbox_transaction(self._connection, tenant, write=write) as cursor:
            yield cursor, tenant

    @staticmethod
    def _read(cursor, tenant, at):
        cursor.execute("""SELECT s.id, s.tenant_id, s.price_version_id, s.started_at, s.trial_ends_at,
            c.cancelled_at, p.plan, p.amount_minor, p.currency, p.interval, p.api_allowance
            FROM omnixat_sandbox.subscriptions s
            JOIN omnixat_sandbox.price_terms p ON p.id=s.price_version_id
            LEFT JOIN omnixat_sandbox.cancellations c ON c.tenant_id=s.tenant_id AND c.subscription_id=s.id
            WHERE s.tenant_id=%s""", (tenant,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError("Sandbox subscription not found")
        if at < row["started_at"] or (row["cancelled_at"] is not None and at < row["cancelled_at"]):
            raise ValueError("Sandbox clock precedes stored event")
        if row["cancelled_at"] is not None:
            state = "cancelled"
        elif row["trial_ends_at"] is None:
            state = "pending"
        else:
            state = "trialing" if at < row["trial_ends_at"] else "trial_expired"
        return SandboxSubscription(**row, state=state)

    def get(self, actor, tenant_id):
        with self._unit(actor, tenant_id) as (cursor, tenant):
            return self._read(cursor, tenant, self._now())

    def start(self, actor, tenant_id, *, plan, interval):
        with self._unit(actor, tenant_id, write=True) as (cursor, tenant):
            plan = _plan_code(plan)
            if interval not in ("month", "year"):
                raise ValueError("Invalid interval")
            at = self._now()
            cursor.execute("""SELECT id, trial_days FROM omnixat_sandbox.price_terms
                WHERE plan=%s AND interval=%s AND effective_at<=%s
                ORDER BY effective_at DESC LIMIT 1""", (plan, interval, at))
            price = cursor.fetchone()
            if price is None:
                raise KeyError("No effective sandbox price")
            try:
                end = at + timedelta(days=price["trial_days"]) if price["trial_days"] else None
            except OverflowError as exc:
                raise ValueError("Trial deadline outside supported dates") from exc
            cursor.execute("""INSERT INTO omnixat_sandbox.subscriptions
                (tenant_id, id, price_version_id, started_at, trial_ends_at, started_by)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id) DO NOTHING RETURNING id""",
                           (tenant, uuid4(), price["id"], at, end, actor.user_id))
            if cursor.fetchone() is None:
                raise SandboxSubscriptionConflict("Sandbox subscription already exists")
            return self._read(cursor, tenant, at)

    def cancel(self, actor, tenant_id):
        with self._unit(actor, tenant_id, write=True) as (cursor, tenant):
            at = self._now()
            current = self._read(cursor, tenant, at)
            if current.state == "cancelled":
                return current
            if current.state == "trial_expired":
                raise SandboxSubscriptionConflict("Sandbox trial already expired")
            cursor.execute("""INSERT INTO omnixat_sandbox.cancellations
                (tenant_id, subscription_id, cancelled_at, cancelled_by)
                VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id) DO NOTHING""",
                           (tenant, current.id, at, actor.user_id))
            return self._read(cursor, tenant, self._now())
