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
    answer_path = os.environ.get('OMNIXAT_CSV_ANSWER_DSN_FILE')
    answer_dsn = _file(answer_path,secret=True) if answer_path else None
    csv_request_path = os.environ.get('OMNIXAT_CSV_REQUEST_DSN_FILE')
    csv_request_dsn = _file(csv_request_path,secret=True) if csv_request_path else None
    csv_status_path = os.environ.get('OMNIXAT_CSV_REQUEST_STATUS_DSN_FILE')
    csv_status_dsn = _file(csv_status_path,secret=True) if csv_status_path else None
    draft_path = os.environ.get('OMNIXAT_EXPENSE_DRAFT_REVIEW_DSN_FILE')
    draft_dsn = _file(draft_path,secret=True) if draft_path else None
    preparation_path = os.environ.get('OMNIXAT_EXPENSE_PREPARATION_DSN_FILE')
    preparation_dsn = _file(preparation_path,secret=True) if preparation_path else None
    observation_path=os.environ.get('OMNIXAT_JOURNAL_OBSERVATION_DSN_FILE')
    observation_dsn=_file(observation_path,secret=True) if observation_path else None
    journal_dsns = {}
    for operation in ('read','preview','write'):
        path = os.environ.get('OMNIXAT_EXPENSE_JOURNAL_'+operation.upper()+'_DSN_FILE')
        journal_dsns[operation] = _file(path,secret=True) if path else None
    funding_read_path = os.environ.get('OMNIXAT_EXPENSE_FUNDING_READ_DSN_FILE')
    funding_read_dsn = _file(funding_read_path,secret=True) if funding_read_path else None
    funding_write_path = os.environ.get('OMNIXAT_EXPENSE_FUNDING_WRITE_DSN_FILE')
    funding_write_dsn = _file(funding_write_path,secret=True) if funding_write_path else None
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
                      csv_review_connection_factory=factory(review_dsn) if review_dsn else None,
                      csv_answer_connection_factory=factory(answer_dsn) if answer_dsn else None,
                      csv_request_connection_factory=factory(csv_request_dsn) if csv_request_dsn else None,
                      csv_request_status_connection_factory=factory(csv_status_dsn) if csv_status_dsn else None,
                      expense_draft_connection_factory=factory(draft_dsn) if draft_dsn else None,
                      expense_preparation_connection_factory=factory(preparation_dsn) if preparation_dsn else None,
                      expense_funding_read_connection_factory=factory(funding_read_dsn) if funding_read_dsn else None,
                      expense_funding_write_connection_factory=factory(funding_write_dsn) if funding_write_dsn else None,
                      journal_observation_connection_factory=factory(observation_dsn) if observation_dsn else None,
                      **{"expense_journal_"+operation+"_connection_factory":factory(dsn) if dsn else None
                         for operation,dsn in journal_dsns.items()})
