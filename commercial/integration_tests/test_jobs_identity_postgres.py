"""Real signed tokens and constrained PostgreSQL roles, using fictional records."""
import time
from hashlib import sha256
from dataclasses import replace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import jwt
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.identity import AuthenticationError
from omnixat_core.jobs_identity_postgres import AuthenticatedJobStore
from omnixat_core.job_tasks import EvidencePreparationTask
from omnixat_core.preparation_postgres import inspect_preparation_evidence
from omnixat_core.evidence_extraction_postgres import EvidenceNotEligible, read_evidence_for_extraction
from test_identity_postgres import MembershipFixture


class AuthenticatedJobsTests(MembershipFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for suffix, grants in {
            'job_gate': ['USAGE ON SCHEMA omnixat_extraction',
                         'EXECUTE ON FUNCTION omnixat_extraction.read_eligible_original(uuid,uuid)'],
            'job_auth': ['USAGE ON SCHEMA omnixat', 'SELECT ON omnixat.identities,omnixat.memberships'],
            'job_data': ['USAGE ON SCHEMA omnixat',
                         'SELECT,INSERT,UPDATE ON omnixat.agent_jobs',
                         'SELECT ON omnixat.tenants,omnixat.organisations,omnixat.evidence_registrations',
                         'SELECT,INSERT ON omnixat.notes,omnixat.record_creations,omnixat.agent_job_note_effects,'
                         'omnixat.agent_job_failures,omnixat.agent_job_evidence_tasks'],
        }.items():
            name, password = cls.role + '_' + suffix, uuid4().hex
            role = sql.Identifier(name)
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE')
                              .format(role, sql.Literal(password)))
            cls.addClassCleanup(cls.drop_role, name)
            for grant in grants:
                cls.owner.execute(sql.SQL('GRANT ' + grant + ' TO {}').format(role))
            setattr(cls, suffix + '_role', name)
            setattr(cls, suffix + '_dsn', make_conninfo(cls.admin.info.dsn, dbname=cls.database, user=name, password=password))

    @classmethod
    def drop_role(cls, name):
        cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(name)))
        cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))

    def setUp(self):
        super().setUp()
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s", (self.user,))
        self.identity_connection = psycopg.connect(self.job_auth_dsn, autocommit=True)
        self.job_connection = psycopg.connect(self.job_data_dsn, autocommit=True)
        self.addCleanup(self.identity_connection.close)
        self.addCleanup(self.job_connection.close)
        self.jobs = AuthenticatedJobStore(self.identity_connection, self.job_connection, self.verifier)
        self.gate_connection = psycopg.connect(self.job_gate_dsn, autocommit=True)
        self.addCleanup(self.gate_connection.close)
        self.owner.execute("DELETE FROM omnixat_extraction.active_scan_policy")
        self.original = b'Fictional document,12.34\r\n'
        evidence = uuid4()
        self.owner.execute("""INSERT INTO omnixat.evidence_registrations
            (tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by)
            VALUES (%s,%s,%s,%s,'text/csv',%s,'fictional-register')
        """, (self.a, evidence, self.org, sha256(self.original).digest(), len(self.original)))
        self.task = EvidencePreparationTask(self.org, evidence, sha256(self.original).digest())

    def create(self, token=None):
        return self.jobs.create_evidence_task(token or self.token(), self.a, 'fictional-task', self.task)

    def operations(self, token, job, lease):
        return [lambda: self.create(token),
                lambda: self.jobs.get(token, self.a, job),
                lambda: self.jobs.get_evidence_task(token, self.a, job),
                lambda: self.jobs.retry_state(token, self.a, job),
                lambda: self.jobs.claim(token, self.a, job),
                lambda: self.jobs.checkpoint(token, self.a, job, lease, {'step': 'late'}),
                lambda: self.jobs.cancel(token, self.a, job),
                lambda: self.jobs.fail(token, self.a, job, lease, 'unexpected_error', retryable=False),
                lambda: self.jobs.create_note_effect(token, self.a, job, lease, 'note', self.org, 'Fictional note'),
                lambda: self.jobs.get_claimed_evidence_task(token, self.a, job, lease)]

    def test_signed_agent_lifecycle_uses_persisted_actor_and_shared_effect_receipts(self):
        token = self.token(role='owner', staff_role='platform_owner', actor_kind='human')
        job = self.create(token)
        lease = self.jobs.claim(token, self.a, job)
        self.assertEqual(self.jobs.get_evidence_task(token, self.a, job), self.task)
        self.jobs.checkpoint(token, self.a, job, lease, {'step': 'prepared'})
        receipt = self.jobs.create_note_effect(token, self.a, job, lease, 'note', self.org, 'Fictional note')
        self.assertEqual(receipt.created_by, str(self.user))
        failure = self.jobs.fail(token, self.a, job, lease, 'temporary_dependency', retryable=True, retry_after_seconds=0)
        self.assertTrue(failure.will_retry)
        with psycopg.connect(self.job_auth_dsn, autocommit=True) as auth, psycopg.connect(self.job_data_dsn, autocommit=True) as data:
            recovered = AuthenticatedJobStore(auth, data, self.verifier)
            second = recovered.claim(token, self.a, job)
            self.assertNotEqual(second, lease)
            self.assertEqual(recovered.create_note_effect(token, self.a, job, second, 'note', self.org, 'Fictional note'), receipt)
            recovered.checkpoint(token, self.a, job, second, {'step': 'done'}, complete=True)
        self.assertEqual(self.jobs.get(token, self.a, job)['status'], 'completed')
        self.assertEqual(self.jobs.retry_state(token, self.a, job).attempts_started, 2)
        self.assertEqual(self.owner.execute('SELECT created_by,claimed_by FROM omnixat.agent_jobs WHERE id=%s', (job,)).fetchone(),
                         (str(self.user), str(self.user)))

    def test_revocation_denies_every_later_operation_including_replays(self):
        token = self.token()
        job = self.create(token)
        lease = self.jobs.claim(token, self.a, job)
        self.jobs.create_note_effect(token, self.a, job, lease, 'note', self.org, 'Fictional note')
        before = self.owner.execute('SELECT * FROM omnixat.agent_jobs WHERE id=%s', (job,)).fetchone()
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s', (self.user,))
        for index, operation in enumerate(self.operations(token, job, lease)):
            with self.subTest(operation=index), self.assertRaises(AuthenticationError):
                operation()
        self.assertEqual(self.owner.execute('SELECT * FROM omnixat.agent_jobs WHERE id=%s', (job,)).fetchone(), before)

    def test_role_downgrade_allows_reads_but_denies_writes_despite_token_claims(self):
        token = self.token(role='owner', tenant_role='owner')
        job = self.create(token)
        lease = self.jobs.claim(token, self.a, job)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s", (self.user,))
        self.assertEqual(self.jobs.get(token, self.a, job)['status'], 'running')
        self.assertEqual(self.jobs.get_evidence_task(token, self.a, job), self.task)
        self.assertEqual(self.jobs.retry_state(token, self.a, job).attempts_started, 1)
        operations = self.operations(token, job, lease)
        for index in [0, 4, 5, 6, 7, 8, 9]:
            with self.subTest(operation=index), self.assertRaises(PermissionError):
                operations[index]()

    def test_invalid_expired_and_wrong_audience_tokens_never_reach_job_storage(self):
        for token in ['invalid', self.token(aud='wrong'), self.token(sub='unknown'),
                      self.token(iat=int(time.time())-100, exp=int(time.time())-1),
                      jwt.encode({'sub': self.subject}, self.key, algorithm='RS256', headers={'kid':'fictional','typ':'JWT'})]:
            with self.subTest(token_kind='fictional-invalid'), self.assertRaises(AuthenticationError):
                self.create(token)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_jobs WHERE tenant_id=%s', (self.a,)).fetchone(), (0,))

    def test_disabled_identity_and_token_cutoff_are_checked_on_next_call(self):
        token = self.token()
        job = self.create(token)
        for assignment in ['disabled_at=now()', 'disabled_at=NULL,tokens_valid_after=' + str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET ' + assignment + ' WHERE id=%s', (self.user,))
            with self.assertRaises(AuthenticationError):
                self.jobs.get(token, self.a, job)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s', (self.user,))
        self.assertEqual(self.jobs.get(token, self.a, job)['status'], 'queued')

    def test_scopes_and_cross_tenant_object_access_remain_restricted(self):
        token = self.token()
        job = self.create(token)
        read_only = self.token(scope='records:read filing:approve')
        self.assertEqual(self.jobs.get(read_only, self.a, job)['status'], 'queued')
        with self.assertRaises(PermissionError):
            self.jobs.claim(read_only, self.a, job)
        with self.assertRaises(PermissionError):
            self.create(self.token(scope='records:write'))
        with self.assertRaises(AuthenticationError):
            self.jobs.get(token, self.b, job)
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.b, self.user))
        with self.assertRaises(KeyError):
            self.jobs.get(token, self.b, job)
        with self.assertRaises(ValueError):
            self.jobs.claim(token, self.b, job)
        self.assertEqual(self.jobs.get(token, self.a, job)['status'], 'queued')

    def test_second_identity_cannot_use_first_workers_lease_but_can_recover(self):
        first_token = self.token()
        job = self.create(first_token)
        lease = self.jobs.claim(first_token, self.a, job)
        receipt = self.jobs.create_note_effect(first_token, self.a, job, lease, 'note', self.org, 'Fictional note')
        second_user = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'second-agent','agent')",
                           (second_user, self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.a, second_user))
        second_token = self.token(sub='second-agent')
        for operation in [lambda: self.jobs.get_claimed_evidence_task(second_token, self.a, job, lease),
                          lambda: self.jobs.checkpoint(second_token, self.a, job, lease, {}),
                          lambda: self.jobs.fail(second_token, self.a, job, lease, 'unexpected_error', retryable=False),
                          lambda: self.jobs.create_note_effect(second_token, self.a, job, lease, 'note', self.org, 'Fictional note')]:
            with self.assertRaises(ValueError):
                operation()
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
        recovered = self.jobs.claim(second_token, self.a, job)
        self.assertEqual(self.jobs.create_note_effect(second_token, self.a, job, recovered, 'note', self.org, 'Fictional note'), receipt)
        self.jobs.checkpoint(second_token, self.a, job, recovered, {}, complete=True)

    def test_separate_minimal_identity_role_context_cleanup_and_failure_before_mutation(self):
        token = self.token()
        job = self.create(token)
        for connection in [self.identity_connection, self.job_connection]:
            self.assertEqual(connection.execute("SELECT NULLIF(current_setting('omnixat.tenant_id',true),'')").fetchone(), (None,))
        self.assertEqual(self.identity_connection.execute('SELECT count(*) FROM omnixat.identities').fetchone(), (0,))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.identity_connection.execute('SELECT * FROM omnixat.agent_jobs')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.job_connection.execute('SELECT * FROM omnixat.identities')
        self.owner.execute(sql.SQL('REVOKE SELECT ON omnixat.memberships FROM {}').format(sql.Identifier(self.job_auth_role)))
        try:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.jobs.claim(token, self.a, job)
        finally:
            self.owner.execute(sql.SQL('GRANT SELECT ON omnixat.memberships TO {}').format(sql.Identifier(self.job_auth_role)))
        self.assertEqual(self.jobs.get(token, self.a, job)['status'], 'queued')
        self.assertEqual(self.jobs.retry_state(token, self.a, job).attempts_started, 0)
        unsafe = AuthenticatedJobStore(self.owner, self.job_connection, self.verifier)
        with self.assertRaises(PermissionError):
            unsafe.get(token, self.a, job)

    def test_authenticated_terminal_receipts_replay_only_with_current_authority(self):
        token = self.token()
        cancelled = self.create(token)
        receipt = self.jobs.cancel(token, self.a, cancelled)
        self.assertEqual(receipt.cancelled_by, str(self.user))
        self.assertEqual(self.jobs.cancel(token, self.a, cancelled), receipt)
        failed = self.jobs.create_evidence_task(token, self.a, 'failed-task', self.task)
        lease = self.jobs.claim(token, self.a, failed)
        failure = self.jobs.fail(token, self.a, failed, lease, 'invalid_input', retryable=False)
        self.assertFalse(failure.will_retry)
        self.assertEqual(self.jobs.fail(token, self.a, failed, lease, 'invalid_input', retryable=False), failure)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s', (self.user,))
        with self.assertRaises(AuthenticationError):
            self.jobs.cancel(token, self.a, cancelled)
        with self.assertRaises(AuthenticationError):
            self.jobs.fail(token, self.a, failed, lease, 'invalid_input', retryable=False)

    def admitted_source(self):
        self.owner.execute('INSERT INTO omnixat.evidence_quarantine(tenant_id,evidence_id,original_bytes) VALUES (%s,%s,%s)',
                           (self.a, self.task.evidence_id, self.original))
        self.owner.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
            (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
            VALUES (%s,%s,%s,%s,'fictional-v1','clean')
        """, (self.a, self.task.evidence_id, self.task.content_sha256, len(self.original)))

    def inspect(self, token, job, lease):
        return inspect_preparation_evidence(self.jobs, self.gate_connection, token, self.a, job, lease)

    def test_inspection_saves_only_metadata_and_repeats_after_recovery_with_fresh_gate(self):
        self.admitted_source()
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        result = self.inspect(token, job, lease)
        self.assertEqual((result.evidence_id, result.organisation_id, result.content_sha256, result.byte_size),
                         (str(self.task.evidence_id), str(self.org), self.task.content_sha256.hex(), len(self.original)))
        self.assertFalse(hasattr(result, 'original_bytes'))
        saved = self.jobs.get(token, self.a, job)
        self.assertEqual(saved['status'], 'running')
        self.assertEqual(saved['checkpoint']['step'], 'evidence_inspected')
        self.assertNotIn(self.original.decode(), str(saved))
        self.assertEqual(self.inspect(token, job, lease), result)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
        with psycopg.connect(self.job_auth_dsn, autocommit=True) as auth, psycopg.connect(self.job_data_dsn, autocommit=True) as data:
            recovered = AuthenticatedJobStore(auth, data, self.verifier)
            current = recovered.claim(token, self.a, job)
            self.assertEqual(inspect_preparation_evidence(recovered, self.gate_connection, token, self.a, job, current), result)
        self.owner.execute('DELETE FROM omnixat_extraction.active_scan_policy')
        with self.assertRaises(EvidenceNotEligible):
            self.inspect(token, job, current)
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], saved['checkpoint'])

    def test_inspection_rejects_non_current_claims_and_permissions_before_gate(self):
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        with patch('omnixat_core.preparation_postgres.read_evidence_for_extraction', side_effect=AssertionError('gate must not run')):
            with self.assertRaises(ValueError):
                self.inspect(token, job, str(uuid4()))
            with self.assertRaises(PermissionError):
                self.inspect(self.token(scope='records:read'), job, lease)
            with self.assertRaises(PermissionError):
                self.inspect(self.token(scope='records:write'), job, lease)
            with self.assertRaises(AuthenticationError):
                inspect_preparation_evidence(self.jobs, self.gate_connection, token, self.b, job, lease)
            self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
            with self.assertRaises(ValueError):
                self.inspect(token, job, lease)
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {})

    def test_inspection_gate_rejects_missing_original_policy_verdict_and_active_scan(self):
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        with self.assertRaises(EvidenceNotEligible):
            self.inspect(token, job, lease)
        self.admitted_source()
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'")
        with self.assertRaises(EvidenceNotEligible):
            self.inspect(token, job, lease)
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v1'")
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
            (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
            VALUES (%s,%s,%s,%s,'fictional-v1','blocked')
        """, (self.a, self.task.evidence_id, self.task.content_sha256, len(self.original)))
        with self.assertRaises(EvidenceNotEligible):
            self.inspect(token, job, lease)
        self.owner.execute("DELETE FROM omnixat.evidence_scan_verdicts WHERE tenant_id=%s AND verdict='blocked'", (self.a,))
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_claims VALUES
            (%s,%s,'fictional-v1',%s,clock_timestamp()+interval '1 minute')
        """, (self.a, self.task.evidence_id, uuid4()))
        with self.assertRaises(EvidenceNotEligible):
            self.inspect(token, job, lease)
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {})

    def test_inspection_verifies_exact_task_fingerprint_and_evidence_identity(self):
        self.admitted_source()
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        original = read_evidence_for_extraction(self.gate_connection, self.a, self.org, self.task.evidence_id)
        for modified in [replace(original, content_sha256='ff'*32), replace(original, evidence_id=uuid4())]:
            with patch('omnixat_core.preparation_postgres.read_evidence_for_extraction', return_value=modified):
                with self.assertRaises(EvidenceNotEligible):
                    self.inspect(token, job, lease)
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {})

    def test_inspection_drops_progress_if_cancelled_expired_or_superseded_during_read(self):
        self.admitted_source()
        token = self.token()
        for change in ['cancel', 'expire', 'supersede']:
            job = self.jobs.create_evidence_task(token, self.a, change, self.task)
            lease = self.jobs.claim(token, self.a, job)
            def read_then_change(*args):
                admitted = read_evidence_for_extraction(*args)
                if change == 'cancel':
                    self.jobs.cancel(token, self.a, job)
                else:
                    self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
                    if change == 'supersede':
                        self.jobs.claim(token, self.a, job)
                return admitted
            with self.subTest(change=change), patch('omnixat_core.preparation_postgres.read_evidence_for_extraction', side_effect=read_then_change):
                with self.assertRaises(ValueError):
                    self.inspect(token, job, lease)
            self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {})

    def test_inspection_rechecks_revocation_role_and_token_cutoff_after_read(self):
        self.admitted_source()
        token = self.token()
        for change in ['revoke', 'downgrade', 'cutoff']:
            job = self.jobs.create_evidence_task(token, self.a, change, self.task)
            lease = self.jobs.claim(token, self.a, job)
            def read_then_change(*args):
                admitted = read_evidence_for_extraction(*args)
                if change == 'cutoff':
                    self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=%s WHERE id=%s', (self.iat, self.user))
                else:
                    assignment = 'revoked_at=now()' if change == 'revoke' else "role='viewer'"
                    self.owner.execute('UPDATE omnixat.memberships SET ' + assignment + ' WHERE user_id=%s', (self.user,))
                return admitted
            try:
                with self.subTest(change=change), patch('omnixat_core.preparation_postgres.read_evidence_for_extraction', side_effect=read_then_change):
                    with self.assertRaises(PermissionError):
                        self.inspect(token, job, lease)
            finally:
                self.owner.execute("UPDATE omnixat.memberships SET revoked_at=NULL,role='editor' WHERE user_id=%s", (self.user,))
                self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s', (self.user,))
            self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {})

    def test_inspection_preserves_newer_progress_and_refuses_other_steps_before_read(self):
        self.admitted_source()
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        newer = {'step': 'later-preparation', 'receipt_id': 'fictional-reference'}
        def read_then_advance(*args):
            admitted = read_evidence_for_extraction(*args)
            self.jobs.checkpoint(token, self.a, job, lease, newer)
            return admitted
        with patch('omnixat_core.preparation_postgres.read_evidence_for_extraction', side_effect=read_then_advance):
            with self.assertRaises(ValueError):
                self.inspect(token, job, lease)
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], newer)
        with patch('omnixat_core.preparation_postgres.read_evidence_for_extraction', side_effect=AssertionError('gate must not run')):
            with self.assertRaisesRegex(ValueError, 'cannot replace'):
                self.inspect(token, job, lease)

    def test_conditional_checkpoint_validates_inputs_and_does_not_complete_on_conflict(self):
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        for expected in [[], {'invalid': float('nan')}, {'too_big': 'x'*65537}]:
            with self.assertRaises(ValueError):
                self.jobs.checkpoint(token, self.a, job, lease, {}, expected_progress=expected)
        progress = {'step': 'prepared'}
        self.jobs.checkpoint(token, self.a, job, lease, progress, expected_progress={})
        with self.assertRaises(ValueError):
            self.jobs.checkpoint(token, self.a, job, lease, {'step': 'stale'}, complete=True, expected_progress={})
        self.assertEqual(self.jobs.get(token, self.a, job)['status'], 'running')
        self.jobs.checkpoint(token, self.a, job, lease, {'step': 'done'}, complete=True, expected_progress=progress)
        with self.assertRaises(ValueError):
            self.jobs.get_claimed_evidence_task(token, self.a, job, lease)

    def test_conditional_checkpoints_have_one_winner_across_connections(self):
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        start = Barrier(2)
        def advance(index):
            with psycopg.connect(self.job_auth_dsn, autocommit=True) as auth, psycopg.connect(self.job_data_dsn, autocommit=True) as data:
                jobs = AuthenticatedJobStore(auth, data, self.verifier)
                start.wait(timeout=5)
                try:
                    jobs.checkpoint(token, self.a, job, lease, {'winner': index}, expected_progress={})
                    return index
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(advance, range(2)))
        winners = [outcome for outcome in outcomes if outcome is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {'winner': winners[0]})
