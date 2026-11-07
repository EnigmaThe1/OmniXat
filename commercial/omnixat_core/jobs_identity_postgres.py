"""Signed bearer boundary for internal preparation jobs; no cached authority.

Each call resolves current identity and membership before one existing job unit.
Revocation governs subsequent calls, not work already in flight. No listener,
provider, scheduler, evidence-byte release or filing approval is supplied here.
"""
from .identity_postgres import resolve_record_principal
from .jobs_postgres import PostgresJobStore


class AuthenticatedJobStore:
    def __init__(self, identity_connection, job_connection, verifier):
        self._identity_connection = identity_connection
        self._jobs = PostgresJobStore(job_connection)
        self._verifier = verifier

    def _actor(self, token, tenant, *, write=False):
        return resolve_record_principal(self._identity_connection, self._verifier, token, tenant, write=write)

    def create_evidence_task(self, token, tenant, request_key, task, *, max_attempts=3):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.create_evidence_task(actor, tenant, request_key, task, max_attempts=max_attempts)

    def get(self, token, tenant, job_id):
        return self._jobs.get(self._actor(token, tenant), tenant, job_id)

    def get_evidence_task(self, token, tenant, job_id):
        return self._jobs.get_evidence_task(self._actor(token, tenant), tenant, job_id)

    def save_csv_plan(self, token, tenant, job_id, lease_token, plan):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.save_csv_plan(actor, tenant, job_id, lease_token, plan)

    def get_csv_plan(self, token, tenant, job_id):
        return self._jobs.get_csv_plan(self._actor(token, tenant), tenant, job_id)

    def get_claimed_evidence_task(self, token, tenant, job_id, lease_token):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.get_claimed_evidence_task(actor, tenant, job_id, lease_token)

    def retry_state(self, token, tenant, job_id):
        return self._jobs.retry_state(self._actor(token, tenant), tenant, job_id)

    def claim(self, token, tenant, job_id, *, lease_seconds=60):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.claim(actor, tenant, job_id, lease_seconds=lease_seconds)

    def checkpoint(self, token, tenant, job_id, lease_token, progress, *, complete=False, expected_progress=None):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.checkpoint(actor, tenant, job_id, lease_token, progress,
                                     complete=complete, expected_progress=expected_progress)

    def cancel(self, token, tenant, job_id):
        return self._jobs.cancel(self._actor(token, tenant, write=True), tenant, job_id)

    def fail(self, token, tenant, job_id, lease_token, failure_code, *, retryable, retry_after_seconds=60):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.fail(actor, tenant, job_id, lease_token, failure_code,
                               retryable=retryable, retry_after_seconds=retry_after_seconds)

    def create_note_effect(self, token, tenant, job_id, lease_token, operation_key, organisation_id, body):
        actor = self._actor(token, tenant, write=True)
        return self._jobs.create_note_effect(actor, tenant, job_id, lease_token, operation_key, organisation_id, body)
