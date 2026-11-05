"""PostgreSQL record adapter. Principals must already be server-verified.

RLS is defence in depth against missing predicates, not protection from a compromised
runtime/SQL injection: that role can set tenant context. For signed bearer identity
resolution use identity_postgres; no HTTP transport exists here.
One exclusive, idle autocommit connection per unit of work; never share concurrently.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import re
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from .access import require_tenant

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class CreationConflict(Exception):
    """A creation key was reused with different inputs."""


def validate_creation_key(key):
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{1,128}', key)):
        raise ValueError("Invalid creation key")
    return key


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
def _tenant_transaction(connection, tenant, *, write=False, identity_tables=False,
                        schema='omnixat', tables_required=('tenants', 'organisations', 'notes', 'record_creations')):
    """Internal exclusive transaction; caller must establish authorisation."""
    _idle(connection)
    if identity_tables:
        tables_required += ('identities', 'memberships')
    started = monotonic()
    with connection.transaction():
        # A new snapshot for each statement is required after a competing insert.
        connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        if not write:
            connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("""SELECT set_config('statement_timeout', '5000', true),
                                     set_config('lock_timeout', '1000', true),
                                     set_config('idle_in_transaction_session_timeout', '5000', true)""")
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            role = cursor.fetchone()
            if role["rolsuper"] or role["rolbypassrls"]:
                raise PermissionError("Runtime identity must not bypass row security")
            cursor.execute("""SELECT c.relname, pg_has_role(current_user, c.relowner, 'MEMBER') AS owned,
                                  row_security_active(c.oid) AS protected
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = ANY(%s)""", (schema, list(tables_required)))
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

    def _reserve_creation(self, operation, key, value, parent=None):
        key = validate_creation_key(key)
        key_digest = sha256(key.encode('ascii')).digest() if key is not None else None
        payload_digest = (sha256(json.dumps([1, str(parent) if parent else None, value],
                                           separators=(',', ':')).encode('ascii')).digest()
                          if key is not None else None)
        result_id = uuid4()
        actor = self._actor.user_id
        with self._connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT set_config('omnixat.record_actor', %s, true)", (actor,))
            cursor.execute("""INSERT INTO omnixat.record_creations
                (tenant_id, actor_id, operation, key_digest, payload_digest, organisation_id, note_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, actor_id, operation, key_digest) DO NOTHING
                RETURNING 1""",
                (self._tenant, actor, operation, key_digest, payload_digest,
                 result_id if parent is None else None, result_id if parent is not None else None))
            if cursor.fetchone() is not None:
                return result_id, False
            # A separate READ COMMITTED statement can see a just-committed winner.
            cursor.execute("""SELECT payload_digest, COALESCE(organisation_id, note_id) AS result_id
                FROM omnixat.record_creations
                WHERE tenant_id=%s AND actor_id=%s AND operation=%s AND key_digest=%s""",
                (self._tenant, actor, operation, key_digest))
            existing = cursor.fetchone()
            if existing is None:
                raise RuntimeError("Creation receipt unavailable")
            if existing['payload_digest'] != payload_digest:
                raise CreationConflict("Creation key does not match these inputs")
            return existing['result_id'], True

    def create_organisation(self, display_name, *, idempotency_key=None):
        self._check(write=True)
        result_id, replay = self._reserve_creation('organisation.create', idempotency_key, display_name)
        if replay:
            return self._organisation(result_id)
        return self._one("""INSERT INTO omnixat.organisations
            (tenant_id, id, display_name, created_by) VALUES (%s,%s,%s,%s)
            RETURNING id, display_name, created_by""",
            (self._tenant, result_id, display_name, self._actor.user_id))

    def _organisation(self, organisation_id):
        return self._one("""SELECT id, display_name, created_by FROM omnixat.organisations
            WHERE tenant_id=%s AND id=%s""", (self._tenant, UUID(str(organisation_id))))

    def get_organisation(self, organisation_id):
        self._check()
        return self._organisation(organisation_id)

    def create_note(self, organisation_id, body, *, idempotency_key=None):
        self._check(write=True)
        # Notes require read access to the parent on initial creation and replay.
        require_tenant(self._actor, str(self._tenant), "records:read")
        parent = UUID(str(organisation_id))
        # Validate parent before reserving so a missing parent leaves no receipt.
        self._organisation(parent)
        result_id, replay = self._reserve_creation('note.create', idempotency_key, body, parent)
        if replay:
            return self.get_note(result_id)
        return self._one("""INSERT INTO omnixat.notes
            (tenant_id,id,organisation_id,body,created_by) VALUES (%s,%s,%s,%s,%s)
            RETURNING id, organisation_id, body, created_by""",
            (self._tenant, result_id, parent, body, self._actor.user_id))

    def get_note(self, note_id):
        self._check()
        return self._one("""SELECT id, organisation_id, body, created_by FROM omnixat.notes
            WHERE tenant_id=%s AND id=%s""", (self._tenant, UUID(str(note_id))))
