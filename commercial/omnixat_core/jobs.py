"""Durable agent-job contract using SQLite for local development tests.

Production adapter will use PostgreSQL. This is not authentication or a queue
worker. Use only server-verified Principal objects. Store opaque evidence IDs,
not raw financial documents or credentials, in job payloads/checkpoints.
"""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
from uuid import uuid4
from .access import require_tenant


class JobStore:
    def __init__(self, path, *, clock=time.time):
        self.path = path
        self.clock = clock
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, request_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL, status TEXT NOT NULL,
                checkpoint TEXT NOT NULL, lease_token TEXT, lease_until REAL,
                UNIQUE(tenant, request_key))''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, actor, tenant, request_key, payload):
        require_tenant(actor, tenant, "records:write")
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 200:
            raise ValueError("Bounded idempotency key required")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE tenant=? AND request_key=?", (tenant, request_key)).fetchone()
            if row:
                if row["payload_hash"] != digest:
                    raise ValueError("Idempotency key reused with different payload")
                return row["id"]
            job_id = str(uuid4())
            db.execute("INSERT INTO jobs (id,tenant,request_key,payload_hash,status,checkpoint,lease_token,lease_until) VALUES (?,?,?,?,?,?,?,?)",
                       (job_id, tenant, request_key, digest, "queued", "{}", None, None))
            return job_id

    def get(self, actor, tenant, job_id):
        require_tenant(actor, tenant, "records:read")
        with self.connect() as db:
            row = db.execute("SELECT id,status,checkpoint FROM jobs WHERE tenant=? AND id=?", (tenant, job_id)).fetchone()
            if row is None:
                raise KeyError("Job not found")
            return {"id": row["id"], "status": row["status"], "checkpoint": json.loads(row["checkpoint"])}

    def claim(self, actor, tenant, job_id, *, lease_seconds=60):
        require_tenant(actor, tenant, "records:write")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Lease must be between 1 and 3600 seconds")
        token = str(uuid4())
        now = self.clock()
        with self.connect() as db:
            changed = db.execute('''UPDATE jobs SET status='running', lease_token=?, lease_until=?
                WHERE tenant=? AND id=? AND (status='queued' OR (status='running' AND lease_until<=?))''',
                (token, now + lease_seconds, tenant, job_id, now)).rowcount
            if changed != 1:
                raise ValueError("Job unavailable or already claimed")
        return token

    def checkpoint(self, actor, tenant, job_id, token, progress, *, complete=False):
        require_tenant(actor, tenant, "records:write")
        if not isinstance(progress, dict) or type(complete) is not bool:
            raise ValueError("Structured progress and explicit completion flag required")
        encoded = json.dumps(progress, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Checkpoint too large; store evidence references")
        with self.connect() as db:
            changed = db.execute('''UPDATE jobs SET checkpoint=?, status=?, lease_token=?, lease_until=?
                WHERE tenant=? AND id=? AND status='running' AND lease_token=? AND lease_until>?''',
                (encoded, "completed" if complete else "running", None if complete else token,
                 None if complete else self.clock() + 60, tenant, job_id, token, self.clock())).rowcount
            if changed != 1:
                raise ValueError("Claim expired, superseded or job unavailable")
