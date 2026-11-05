"""Organisation-scoped fingerprints for verified tenant evidence intake."""
from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from .access import require_tenant
from .evidence_intake import EVIDENCE_MEDIA_TYPES, MAX_EVIDENCE_BYTES
from .postgres import _tenant_transaction

_COLUMNS = "id, organisation_id, content_sha256, media_type, byte_size, registered_by, registered_at"
_TABLES = ("organisations", "evidence_registrations")


class EvidenceConflict(Exception):
    """An existing content fingerprint was registered with different metadata."""


@dataclass(frozen=True)
class EvidenceRegistration:
    id: UUID
    organisation_id: UUID
    content_sha256: str
    media_type: str
    byte_size: int
    registered_by: str
    registered_at: datetime


def _registration(row):
    if row is None:
        raise KeyError("Evidence registration not found")
    return EvidenceRegistration(**(row | {"content_sha256": row["content_sha256"].hex()}))


def _authorize(actor, tenant_id, permission):
    require_tenant(actor, tenant_id, permission)
    if actor.staff_role is not None:
        raise PermissionError("Tenant evidence access requires a tenant principal")
    return UUID(tenant_id)


def register_evidence(connection, actor, tenant_id, organisation_id, *, content_sha256, media_type, byte_size):
    """Register metadata computed by trusted intake; never accepts document bytes or a URL."""
    tenant = _authorize(actor, tenant_id, "evidence:register")
    organisation = UUID(str(organisation_id))
    if not isinstance(content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValueError("Expected a lowercase SHA-256 fingerprint")
    if media_type not in EVIDENCE_MEDIA_TYPES:
        raise ValueError("Unsupported evidence media type")
    if type(byte_size) is not int or not 1 <= byte_size <= MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence size outside intake limit")
    if not isinstance(actor.user_id, str) or not actor.user_id.strip() or len(actor.user_id) > 200 or "\x00" in actor.user_id:
        raise ValueError("Invalid registrar identity")
    digest = bytes.fromhex(content_sha256)

    with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT has_any_column_privilege('omnixat.evidence_registrations', 'UPDATE')
                    OR has_table_privilege('omnixat.evidence_registrations', 'DELETE,TRUNCATE')
                    AS mutable
            """)
            if cursor.fetchone()["mutable"]:
                raise PermissionError("Append-only evidence runtime required")
            cursor.execute("SELECT 1 FROM omnixat.organisations WHERE tenant_id=%s AND id=%s",
                           (tenant, organisation))
            if cursor.fetchone() is None:
                raise KeyError("Organisation not found")
            cursor.execute("""
                INSERT INTO omnixat.evidence_registrations
                    (tenant_id, id, organisation_id, content_sha256, media_type, byte_size, registered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, organisation_id, content_sha256) DO NOTHING
                RETURNING
            """ + _COLUMNS, (tenant, uuid4(), organisation, digest, media_type, byte_size, actor.user_id))
            row = cursor.fetchone()
            if row is None:
                # A fresh READ COMMITTED statement sees the concurrent winner.
                cursor.execute("SELECT " + _COLUMNS + """
                    FROM omnixat.evidence_registrations
                    WHERE tenant_id=%s AND organisation_id=%s AND content_sha256=%s
                """, (tenant, organisation, digest))
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Evidence registration unavailable")
                if (row["media_type"], row["byte_size"]) != (media_type, byte_size):
                    raise EvidenceConflict("Existing evidence has different metadata")
            return _registration(row)


def get_evidence(connection, actor, tenant_id, organisation_id, evidence_id):
    """Return only registration metadata for the explicitly scoped organisation."""
    tenant = _authorize(actor, tenant_id, "evidence:read")
    with _tenant_transaction(connection, tenant, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT " + _COLUMNS + """
                FROM omnixat.evidence_registrations WHERE tenant_id=%s AND organisation_id=%s AND id=%s
            """, (tenant, UUID(str(organisation_id)), UUID(str(evidence_id))))
            return _registration(cursor.fetchone())
