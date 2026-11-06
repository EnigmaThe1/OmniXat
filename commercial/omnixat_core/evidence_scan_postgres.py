"""Scanner worker boundary; does not make evidence available for extraction."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from typing import Callable
from uuid import UUID, uuid4

from psycopg import Error as DatabaseError
from psycopg.rows import dict_row

from .evidence_intake import MAX_EVIDENCE_BYTES
from .postgres import _tenant_transaction

_TABLES = (
    "evidence_registrations", "evidence_quarantine", "evidence_scan_verdicts", "evidence_scan_claims",
)


class EvidenceScanError(Exception):
    """Scanning did not produce a usable durable decision."""


class EvidenceScanBusy(EvidenceScanError):
    """Another worker currently owns the scan claim."""


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


def _receipt(cursor, scope):
    cursor.execute("""
        SELECT verdict, recorded_at FROM omnixat.evidence_scan_verdicts
        WHERE tenant_id=%s AND evidence_id=%s AND policy_version=%s
        ORDER BY (verdict='blocked') DESC LIMIT 1
    """, scope)
    row = cursor.fetchone()
    return EvidenceScanReceipt(scope[1], scope[2], row["verdict"], row["recorded_at"]) if row else None


def _drop_claim(cursor, scope, token, *, require_live=False):
    query = """
        DELETE FROM omnixat.evidence_scan_claims
        WHERE tenant_id=%s AND evidence_id=%s AND policy_version=%s AND lease_token=%s
    """
    if require_live:
        # Take the row lock before checking the database clock in DELETE.
        cursor.execute("""
            SELECT lease_token FROM omnixat.evidence_scan_claims
            WHERE tenant_id=%s AND evidence_id=%s AND policy_version=%s AND lease_token=%s
            FOR UPDATE
        """, (*scope, token))
        if cursor.fetchone() is None:
            return False
        query += " AND expires_at > clock_timestamp()"
    cursor.execute(query, (*scope, token))
    return cursor.rowcount == 1


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
    scope = (tenant, evidence, policy_version)
    token = uuid4()
    with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
        with connection.cursor(row_factory=dict_row) as cursor:
            _require_scanner_role(cursor)
            cursor.execute("""
                SELECT q.content_sha256, q.byte_size, r.media_type
                FROM omnixat.evidence_quarantine q
                JOIN omnixat.evidence_registrations r ON (r.tenant_id, r.id) = (q.tenant_id, q.evidence_id)
                WHERE q.tenant_id=%s AND q.evidence_id=%s AND r.organisation_id=%s
            """, (tenant, evidence, organisation))
            row = cursor.fetchone()
            if row is None:
                raise KeyError("Quarantined evidence not found")
            recorded = _receipt(cursor, scope)
            if recorded is not None:
                return recorded

            cursor.execute("""
                INSERT INTO omnixat.evidence_scan_claims AS claim
                    (tenant_id,evidence_id,policy_version,lease_token,expires_at)
                VALUES (%s,%s,%s,%s,clock_timestamp() + interval '120 seconds')
                ON CONFLICT (tenant_id,evidence_id,policy_version) DO UPDATE
                    SET lease_token=EXCLUDED.lease_token,
                        expires_at=clock_timestamp() + interval '120 seconds'
                    WHERE claim.expires_at <= clock_timestamp()
            """, (*scope, token))
            if cursor.rowcount != 1:
                raise EvidenceScanBusy("Evidence scan already claimed")
            # A previous worker could have committed between our first read and claim.
            recorded = _receipt(cursor, scope)
            if recorded is not None:
                _drop_claim(cursor, scope, token)
                return recorded
            cursor.execute("""
                SELECT original_bytes FROM omnixat.evidence_quarantine
                WHERE tenant_id=%s AND evidence_id=%s
            """, (tenant, evidence))
            original = cursor.fetchone()["original_bytes"]

    try:
        if not isinstance(original, bytes) or not 1 <= len(original) == row["byte_size"] <= MAX_EVIDENCE_BYTES or (
            sha256(original).digest() != row["content_sha256"]
        ):
            raise EvidenceScanError("Quarantine integrity check failed")
        # Do not hold a database transaction during scanner work.
        try:
            verdict = scan(original, row["media_type"])
        except Exception:
            raise EvidenceScanError("Scanner unavailable") from None
        if type(verdict) is not str or verdict not in ("clean", "blocked"):
            raise EvidenceScanError("Scanner did not return a supported verdict")

        with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
            with connection.cursor(row_factory=dict_row) as cursor:
                _require_scanner_role(cursor)
                if not _drop_claim(cursor, scope, token, require_live=True):
                    raise EvidenceScanError("Evidence scan claim expired or was replaced")
                cursor.execute("""
                    INSERT INTO omnixat.evidence_scan_verdicts
                        (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id,evidence_id,policy_version,verdict) DO NOTHING
                """, (tenant, evidence, row["content_sha256"], row["byte_size"], policy_version, verdict))
                recorded = _receipt(cursor, scope)
                if recorded is None:
                    raise EvidenceScanError("Scanner verdict unavailable")
                return recorded
    except Exception:
        try:
            with _tenant_transaction(connection, tenant, write=True, tables_required=_TABLES):
                with connection.cursor() as cursor:
                    _drop_claim(cursor, scope, token)
        except DatabaseError:
            # Lost database access is recoverable through lease expiry.
            pass
        raise
