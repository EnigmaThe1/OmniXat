"""PostgreSQL record adapter. Principals must already be server-verified.

RLS is defence in depth against missing predicates, not protection from a compromised
runtime/SQL injection: that role can set tenant context. For signed bearer identity
resolution use identity_postgres; no HTTP transport exists here.
One exclusive, idle autocommit connection per unit of work; never share concurrently.
"""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from .access import require_tenant

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _idle(connection):
    if not connection.autocommit or connection.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("Exclusive idle autocommit connection required")


def migrate(connection):
    """Atomic, checksum-checked migrations; explicitly invoked with migration owner."""
    _idle(connection)
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(724190026)")
        connection.execute("""CREATE TABLE IF NOT EXISTS public.omnixat_schema_migrations (
            version text PRIMARY KEY, digest text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        connection.execute("REVOKE ALL ON public.omnixat_schema_migrations FROM PUBLIC")
        applied = dict(connection.execute(
            "SELECT version, digest FROM public.omnixat_schema_migrations").fetchall())
        files = sorted(MIGRATIONS.glob("[0-9]*.sql"))
        if not files:
            raise ValueError("Migration files unavailable")
        if set(applied) - {p.name for p in files}:
            raise ValueError("Database contains unknown migrations")
        for path in files:
            source = path.read_bytes()
            digest = sha256(source).hexdigest()
            if path.name in applied:
                if applied[path.name] != digest:
                    raise ValueError("Applied migration checksum mismatch")
                continue
            connection.execute(source.decode("utf-8"))
            connection.execute("INSERT INTO public.omnixat_schema_migrations VALUES (%s, %s, DEFAULT)",
                               (path.name, digest))


@contextmanager
def tenant_records(connection, actor, tenant_id, *, write=False):
    """Bind one verified tenant transaction and reject privileged DB identities."""
    if type(write) is not bool:
        raise ValueError("Explicit write flag required")
    require_tenant(actor, tenant_id, "records:write" if write else "records:read")
    tenant = UUID(tenant_id)
    with _tenant_transaction(connection, tenant, write=write):
        records = TenantRecords(connection, actor, tenant, write)
        try:
            yield records
        finally:
            records._active = False


@contextmanager
def _tenant_transaction(connection, tenant, *, write=False, identity_tables=False):
    """Internal exclusive transaction; caller must establish authorisation."""
    _idle(connection)
    tables_required = ('tenants', 'organisations', 'notes')
    if identity_tables:
        tables_required += ('identities', 'memberships')
    started = monotonic()
    with connection.transaction():
        connection.execute("""SELECT set_config('statement_timeout', '5000', true),
                                     set_config('lock_timeout', '1000', true),
                                     set_config('idle_in_transaction_session_timeout', '5000', true)""")
        if not write:
            connection.execute("SET TRANSACTION READ ONLY")
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            role = cursor.fetchone()
            if role["rolsuper"] or role["rolbypassrls"]:
                raise PermissionError("Runtime identity must not bypass row security")
            cursor.execute("""SELECT c.relname, pg_has_role(current_user, c.relowner, 'MEMBER') AS owned,
                                  row_security_active(c.oid) AS protected
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'omnixat' AND c.relname = ANY(%s)""", (list(tables_required),))
            tables = cursor.fetchall()
            if len(tables) != len(tables_required) or any(t["owned"] or not t["protected"] for t in tables):
                raise PermissionError("Non-owner runtime and active row security required")
            cursor.execute("SELECT set_config('omnixat.tenant_id', %s, true)", (str(tenant),))
        yield
        if monotonic() - started > 10:
            raise TimeoutError("Record transaction exceeded commit deadline")


class TenantRecords:
    def __init__(self, connection, actor, tenant, write):
        self._connection, self._actor, self._tenant, self._write = connection, actor, tenant, write
        self._active = True

    def _check(self, write=False):
        require_tenant(self._actor, str(self._tenant), "records:write" if write else "records:read")
        if not self._active or self._connection.info.transaction_status != TransactionStatus.INTRANS:
            raise RuntimeError("Record unit of work has ended")
        if write and not self._write:
            raise PermissionError("Read-only record unit of work")

    def _one(self, query, params):
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row is None:
                raise KeyError("Record not found")
            return row

    def create_organisation(self, display_name):
        self._check(write=True)
        return self._one("""INSERT INTO omnixat.organisations
            (tenant_id, id, display_name, created_by) VALUES (%s,%s,%s,%s)
            RETURNING id, display_name, created_by""",
            (self._tenant, uuid4(), display_name, self._actor.user_id))

    def get_organisation(self, organisation_id):
        self._check()
        return self._one("""SELECT id, display_name, created_by FROM omnixat.organisations
            WHERE tenant_id=%s AND id=%s""", (self._tenant, UUID(str(organisation_id))))

    def create_note(self, organisation_id, body):
        self._check(write=True)
        # Same not-found result for nonexistent and other-tenant organisation IDs.
        self.get_organisation(organisation_id)
        return self._one("""INSERT INTO omnixat.notes
            (tenant_id,id,organisation_id,body,created_by) VALUES (%s,%s,%s,%s,%s)
            RETURNING id, organisation_id, body, created_by""",
            (self._tenant, uuid4(), UUID(str(organisation_id)), body, self._actor.user_id))

    def get_note(self, note_id):
        self._check()
        return self._one("""SELECT id, organisation_id, body, created_by FROM omnixat.notes
            WHERE tenant_id=%s AND id=%s""", (self._tenant, UUID(str(note_id))))
