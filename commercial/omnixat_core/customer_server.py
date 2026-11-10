"""Explicit ASGI factory for the customer website; no credentials in source."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
from threading import BoundedSemaphore

from cryptography.hazmat.primitives.serialization import load_pem_public_key
import psycopg

from .customer_web import create_app
from .http_api import _pairs
from .identity import AccessTokenVerifier


def _file(path, *, secret=False):
    file = Path(path)
    if secret:
        metadata = file.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValueError('DSN files require private file permissions')
    with file.open('rb') as source:
        content = source.read(65537)
    if not content or len(content)>65536:
        raise ValueError('Configuration file is empty or too large')
    return content.decode('utf-8').strip()


def create_configured_app():
    """Invoke with an operator-managed gateway, pinned keys and separate DB roles."""
    origin = os.environ['OMNIXAT_PUBLIC_ORIGIN']
    issuer, audience = os.environ['OMNIXAT_ACCESS_ISSUER'],os.environ['OMNIXAT_ACCESS_AUDIENCE']
    keys = json.loads(_file(os.environ['OMNIXAT_ACCESS_KEYS_FILE']),object_pairs_hook=_pairs)
    if not isinstance(keys,dict) or not 1 <= len(keys) <= 64:
        raise ValueError('Pinned kid-to-public-PEM mapping required')
    verifier = AccessTokenVerifier(issuer=issuer,audience=audience,
        public_keys={kid:load_pem_public_key(pem.encode('ascii')) for kid,pem in keys.items()})
    record_dsn = _file(os.environ['OMNIXAT_RECORD_DSN_FILE'],secret=True)
    directory_dsn = _file(os.environ['OMNIXAT_DIRECTORY_DSN_FILE'],secret=True)
    status_dsn_path = os.environ.get('OMNIXAT_SCAN_STATUS_DSN_FILE')
    status_dsn = _file(status_dsn_path,secret=True) if status_dsn_path else None
    request_path = os.environ.get('OMNIXAT_SCAN_REQUEST_DSN_FILE')
    request_dsn = _file(request_path,secret=True) if request_path else None
    review_path = os.environ.get('OMNIXAT_CSV_REVIEW_DSN_FILE')
    review_dsn = _file(review_path,secret=True) if review_path else None
    admission = BoundedSemaphore(16)
    def factory(dsn):
        @contextmanager
        def lease():
            if not admission.acquire(timeout=2):
                raise TimeoutError('Database admission unavailable')
            try:
                with psycopg.connect(dsn,autocommit=True,connect_timeout=2,
                                     application_name='omnixat-customer-web') as connection:
                    yield connection
            finally:
                admission.release()
        return lease
    return create_app(verifier=verifier,connection_factory=factory(record_dsn),
                      directory_connection_factory=factory(directory_dsn),public_origin=origin,
                      evidence_quarantine_dir=os.environ.get("OMNIXAT_EVIDENCE_SPOOL_DIR"),
                      scan_status_connection_factory=factory(status_dsn) if status_dsn else None,
                      scan_request_connection_factory=factory(request_dsn) if request_dsn else None,
                      csv_review_connection_factory=factory(review_dsn) if review_dsn else None)
