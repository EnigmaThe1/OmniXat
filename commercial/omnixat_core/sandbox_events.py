"""Local simulator envelope, not a payment provider webhook protocol."""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import re
from uuid import UUID

from .subscriptions_postgres import PostgresSubscriptionSandbox, _sandbox_transaction

_FIELDS = {"tenant_id", "event_id", "subscription_id", "price_version_id", "state"}
_STATES = {"pending", "trialing", "trial_expired", "cancelled", "active"}
_DOMAIN = b"omnixat:sandbox:subscription-snapshot:v1:"


class SandboxEventRejected(ValueError):
    """Invalid or misbound simulator envelope."""


class SandboxEventConflict(ValueError):
    """The event identifier was already used with different bytes."""


@dataclass(frozen=True)
class SandboxEventReceipt:
    event_id: UUID
    subscription_id: UUID
    outcome: str
    reported_state: str
    observed_state: str
    received_at: datetime


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SandboxEventRejected("Duplicate sandbox event field")
        result[key] = value
    return result


class SandboxEventReceiver:
    """One trusted simulator key and tenant per receiver. Does not modify billing."""

    def __init__(self, connection, *, tenant_id, signing_key, clock=lambda: datetime.now(timezone.utc)):
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("At least 32 bytes of simulator key material required")
        self._tenant = UUID(str(tenant_id))
        self._key = signing_key
        self._clock = clock
        self._connection = connection

    def accept(self, body, *, timestamp, signature):
        at = self._clock()
        if not isinstance(at, datetime) or at.utcoffset() is None:
            raise ValueError("Sandbox clock must provide an aware datetime")
        if (type(timestamp) is not int or not 0 <= timestamp <= 253402300799 or
                abs(at.timestamp() - timestamp) > 300 or
                not isinstance(body, bytes) or not 1 <= len(body) <= 2048 or
                not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature)):
            raise SandboxEventRejected("Invalid sandbox event envelope")
        signed = _DOMAIN + str(timestamp).encode("ascii") + b"." + body
        if not hmac.compare_digest(hmac.digest(self._key, signed, "sha256").hex(), signature):
            raise SandboxEventRejected("Invalid sandbox event signature")
        try:
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_fields)
            if not isinstance(payload, dict) or payload.keys() != _FIELDS or any(
                not isinstance(value, str) for value in payload.values()
            ) or payload["state"] not in _STATES:
                raise ValueError("Invalid fields")
            tenant, event, subscription, price = (
                UUID(payload[field]) for field in ("tenant_id", "event_id", "subscription_id", "price_version_id")
            )
        except (ValueError, RecursionError) as exc:
            raise SandboxEventRejected("Invalid sandbox event body") from exc
        if tenant != self._tenant:
            raise SandboxEventRejected("Sandbox event tenant mismatch")

        digest = sha256(body).digest()
        reported = payload["state"]
        with _sandbox_transaction(self._connection, tenant, write=True,
                                  extra_tables=("event_receipts",),
                                  select_only=("price_terms", "subscriptions", "cancellations")) as cursor:
            def existing():
                cursor.execute("""SELECT event_id, subscription_id, outcome, reported_state,
                    observed_state, received_at, body_digest FROM omnixat_sandbox.event_receipts
                    WHERE tenant_id=%s AND event_id=%s""", (tenant, event))
                row = cursor.fetchone()
                if row is None:
                    return None
                if row.pop("body_digest") != digest:
                    raise SandboxEventConflict("Sandbox event ID already used with different bytes")
                return SandboxEventReceipt(**row)

            receipt = existing()
            if receipt is not None:
                return receipt
            current = PostgresSubscriptionSandbox._read(cursor, tenant, at)
            if current.id != subscription:
                raise SandboxEventRejected("Sandbox event subscription mismatch")
            outcome = ("price_mismatch" if price != current.price_version_id else
                       "state_mismatch" if reported != current.state else "matched")
            cursor.execute("""INSERT INTO omnixat_sandbox.event_receipts
                (tenant_id,event_id,subscription_id,body_digest,reported_price_version_id,
                 reported_state,observed_state,outcome,received_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,event_id) DO NOTHING""",
                           (tenant, event, subscription, digest, price, reported, current.state, outcome, at))
            receipt = existing()
            if receipt is None:
                raise RuntimeError("Sandbox event receipt unavailable")
            return receipt
