"""Internal durable quarantine for a bounded, staged evidence original."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_intake import MAX_EVIDENCE_BYTES, QuarantinedEvidence
from .evidence_postgres import EvidenceConflict, _authorize
from .postgres import _tenant_transaction

_TABLES = ("evidence_registrations", "evidence_quarantine")


@dataclass(frozen=True)
class EvidenceQuarantineReceipt:
    evidence_id: UUID
    stored_at: datetime


def store_quarantined_evidence(
    connection, actor, tenant_id, organisation_id, evidence_id, staged: QuarantinedEvidence,
) -> EvidenceQuarantineReceipt:
    """Store an unconsumed staged original; a retry needs a fresh staging context."""
    tenant = _authorize(actor, tenant_id, "evidence:register")
    organisation, evidence = UUID(str(organisation_id)), UUID(str(evidence_id))
    with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT has_column_privilege('omnixat.evidence_quarantine', 'original_bytes', 'SELECT')
                    OR has_any_column_privilege('omnixat.evidence_quarantine', 'UPDATE')
                    OR has_table_privilege('omnixat.evidence_quarantine', 'DELETE,TRUNCATE')
                    AS overprivileged
            """)
            if cursor.fetchone()["overprivileged"]:
                raise PermissionError("Write-only quarantine payload grants required")
            cursor.execute("""
                SELECT content_sha256, byte_size, media_type
                FROM omnixat.evidence_registrations
                WHERE tenant_id=%s AND organisation_id=%s AND id=%s
            """, (tenant, organisation, evidence))
            row = cursor.fetchone()
            if row is None:
                raise KeyError("Evidence registration not found")
            expected_size = row["byte_size"]
            if not 1 <= expected_size <= MAX_EVIDENCE_BYTES or (
                row["content_sha256"].hex(), expected_size, row["media_type"]
            ) != (staged.content_sha256, staged.byte_size, staged.media_type):
                raise EvidenceConflict("Staged evidence does not match registration")

            original = bytearray()
            while len(original) < expected_size:
                requested = min(64 * 1024, expected_size - len(original))
                chunk = staged.read_for_scan(requested)
                if not isinstance(chunk, bytes) or len(chunk) > requested:
                    raise EvidenceConflict("Invalid staged evidence stream")
                if not chunk:
                    break
                original.extend(chunk)
            if len(original) != expected_size or staged.read_for_scan(1) or (
                sha256(original).digest() != row["content_sha256"]
            ):
                raise EvidenceConflict("Staged bytes do not match registration")

            cursor.execute("""
                INSERT INTO omnixat.evidence_quarantine (tenant_id, evidence_id, original_bytes)
                VALUES (%s,%s,%b)
                ON CONFLICT (tenant_id, evidence_id) DO NOTHING
                RETURNING stored_at
            """, (tenant, evidence, original))
            stored = cursor.fetchone()
            if stored is None:
                cursor.execute("""
                    SELECT stored_at FROM omnixat.evidence_quarantine
                    WHERE tenant_id=%s AND evidence_id=%s
                """, (tenant, evidence))
                stored = cursor.fetchone()
            if stored is None:
                raise RuntimeError("Evidence quarantine receipt unavailable")
            return EvidenceQuarantineReceipt(evidence, stored["stored_at"])
