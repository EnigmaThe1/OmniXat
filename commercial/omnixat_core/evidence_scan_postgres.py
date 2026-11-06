"""Scanner worker boundary; does not make evidence available for extraction."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from typing import Callable
from uuid import UUID

from psycopg.rows import dict_row

from .evidence_intake import MAX_EVIDENCE_BYTES
from .postgres import _tenant_transaction

_TABLES = ("evidence_registrations", "evidence_quarantine", "evidence_scan_verdicts")


class EvidenceScanError(Exception):
    """Scanning did not produce a usable durable decision."""


@dataclass(frozen=True)
class EvidenceScanReceipt:
    evidence_id: UUID
    policy_version: str
    verdict: str
    recorded_at: datetime


def _require_scanner_role(cursor):
    cursor.execute("""
        SELECT has_any_column_privilege('omnixat.evidence_quarantine', 'INSERT,UPDATE')
            OR has_table_privilege('omnixat.evidence_quarantine', 'DELETE,TRUNCATE')
            OR has_any_column_privilege('omnixat.evidence_registrations', 'INSERT,UPDATE')
            OR has_table_privilege('omnixat.evidence_registrations', 'DELETE,TRUNCATE')
            OR has_any_column_privilege('omnixat.evidence_scan_verdicts', 'UPDATE')
            OR has_table_privilege('omnixat.evidence_scan_verdicts', 'DELETE,TRUNCATE')
            AS overprivileged
    """)
    if cursor.fetchone()["overprivileged"]:
        raise PermissionError("Dedicated scanner grants required")


def scan_quarantined_evidence(
    connection, tenant_id, organisation_id, evidence_id, *,
    policy_version: str, scan: Callable[[bytes, str], str],
) -> EvidenceScanReceipt:
    """Use a trusted job's scope and server-selected scanner/policy. Never call from a request."""
    if not isinstance(policy_version, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", policy_version,
    ):
        raise ValueError("Invalid scanner policy version")
    tenant, organisation, evidence = (UUID(str(x)) for x in (tenant_id, organisation_id, evidence_id))
    with _tenant_transaction(connection, tenant, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_scanner_role(cursor)
            cursor.execute("""
                SELECT q.content_sha256, q.byte_size, r.media_type, v.verdict, v.recorded_at,
                    CASE WHEN v.verdict IS NULL THEN q.original_bytes END AS original
                FROM omnixat.evidence_quarantine q
                JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
                LEFT JOIN LATERAL (
                    SELECT verdict, recorded_at FROM omnixat.evidence_scan_verdicts
                    WHERE tenant_id=q.tenant_id AND evidence_id=q.evidence_id AND policy_version=%s
                    ORDER BY (verdict='blocked') DESC LIMIT 1
                ) v ON true
                WHERE q.tenant_id=%s AND q.evidence_id=%s AND r.organisation_id=%s
            """, (policy_version, tenant, evidence, organisation))
            row = cursor.fetchone()
    if row is None:
        raise KeyError("Quarantined evidence not found")
    if row["verdict"] is not None:
        return EvidenceScanReceipt(evidence, policy_version, row["verdict"], row["recorded_at"])

    original = row["original"]
    if not isinstance(original, bytes) or not 1 <= len(original) == row["byte_size"] <= MAX_EVIDENCE_BYTES or (
        sha256(original).digest() != row["content_sha256"]
    ):
        raise EvidenceScanError("Quarantine integrity check failed")
    # A blocking or failing scanner must never hold a database transaction open.
    try:
        verdict = scan(original, row["media_type"])
    except Exception:
        raise EvidenceScanError("Scanner unavailable") from None
    if type(verdict) is not str or verdict not in ("clean", "blocked"):
        raise EvidenceScanError("Scanner did not return a supported verdict")

    with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_scanner_role(cursor)
            cursor.execute("""
                INSERT INTO omnixat.evidence_scan_verdicts
                    (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,evidence_id,policy_version,verdict) DO NOTHING
            """, (tenant, evidence, row["content_sha256"], row["byte_size"], policy_version, verdict))
            cursor.execute("""
                SELECT verdict, recorded_at FROM omnixat.evidence_scan_verdicts
                WHERE tenant_id=%s AND evidence_id=%s AND policy_version=%s
                ORDER BY (verdict='blocked') DESC LIMIT 1
            """, (tenant, evidence, policy_version))
            recorded = cursor.fetchone()
            if recorded is None:
                raise EvidenceScanError("Scanner verdict unavailable")
            return EvidenceScanReceipt(evidence, policy_version, recorded["verdict"], recorded["recorded_at"])
