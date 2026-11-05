"""Shared, bounded admission hook for the staff browser qualification app."""
from ipaddress import IPv6Address, ip_address, ip_network
import hmac

from psycopg.rows import tuple_row

from .postgres import _idle

_ACTIONS = frozenset({"login", "callback", "session", "logout"})


def _source_key(key, host):
    if not isinstance(host, str) or "%" in host or len(host) > 45:
        return None
    try:
        address = ip_address(host)
    except ValueError:
        return None
    if isinstance(address, IPv6Address):
        address = address.ipv4_mapped or ip_network((address, 64), strict=False).network_address
    return hmac.digest(key, b"omnixat.staff-admission.v1\x00" + address.packed, "sha256").hex()


class PostgresStaffAdmission:
    """Use a dedicated execute-only connection factory and trusted ASGI client IP."""

    def __init__(self, connection_factory, *, key):
        if not callable(connection_factory) or not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("Connection factory and dedicated 32-byte key required")
        self._connection_factory = connection_factory
        self._key = key

    def __call__(self, request, action):
        if action not in _ACTIONS or request.client is None:
            return False
        source = _source_key(self._key, request.client.host)
        if source is None:
            return False
        with self._connection_factory() as connection:
            _idle(connection)
            with connection.transaction(), connection.cursor(row_factory=tuple_row) as cursor:
                cursor.execute("SET LOCAL statement_timeout = '2s'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
                cursor.execute("SELECT omnixat_staff_admission.admit(%s, %s)", (action, source))
                return cursor.fetchone()[0] is True
