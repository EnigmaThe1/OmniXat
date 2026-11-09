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
from omnixat_core.job_tasks import EvidencePreparationTask, CSVExtractionPlan, ExpensePreparationPlan, JournalPreparationPlan
from omnixat_core.evidence_csv import AmountCell
from omnixat_core.postgres import CreationConflict
from omnixat_core.preparation_postgres import inspect_preparation_evidence, execute_preparation_csv
from omnixat_core.evidence_extraction_postgres import EvidenceNotEligible, read_evidence_for_extraction
from test_identity_postgres import MembershipFixture


class AuthenticatedJobsTests(MembershipFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for suffix, grants in {
            'job_gate': ['USAGE ON SCHEMA omnixat_extraction',
                         'EXECUTE ON FUNCTION omnixat_extraction.read_eligible_original(uuid,uuid)',
                         'EXECUTE ON FUNCTION omnixat_extraction.store_job_csv_result(uuid,text,uuid,uuid,bytea,text,bytea,jsonb)'],
            'job_journal_plan': ['USAGE ON SCHEMA omnixat_extraction',
                            'EXECUTE ON FUNCTION omnixat_extraction.save_job_journal_plan(uuid,text,uuid,bytea,bytea,uuid,uuid,text,uuid,bytea)'],
            'job_expense_summary': ['USAGE ON SCHEMA omnixat_extraction',
                            'EXECUTE ON FUNCTION omnixat_extraction.read_job_expense_summary(uuid,text,uuid,bytea,bytea)'],
            'job_expense': ['USAGE ON SCHEMA omnixat_extraction',
                            'EXECUTE ON FUNCTION omnixat_extraction.create_job_expense_draft(uuid,text,uuid,bytea,bytea)'],
            'job_summary': ['USAGE ON SCHEMA omnixat_extraction',
                            'EXECUTE ON FUNCTION omnixat_extraction.read_job_csv_summary(uuid,text,uuid,bytea)'],
            'job_clarify': ['USAGE ON SCHEMA omnixat_extraction',
                            'EXECUTE ON FUNCTION omnixat_extraction.store_csv_answer(uuid,uuid,uuid,text,integer,integer,text,text)'],
            'job_auth': ['USAGE ON SCHEMA omnixat', 'SELECT ON omnixat.identities,omnixat.memberships'],
            'job_data': ['USAGE ON SCHEMA omnixat',
                         'SELECT,INSERT,UPDATE ON omnixat.agent_jobs',
                         'SELECT ON omnixat.agent_job_journal_plans,omnixat.tenants,omnixat.organisations,omnixat.evidence_registrations,'
                         'omnixat.expense_accounting_periods,omnixat.expense_account_policy',
                         'SELECT,INSERT ON omnixat.notes,omnixat.record_creations,omnixat.agent_job_note_effects,'
                         'omnixat.agent_job_failures,omnixat.agent_job_evidence_tasks,omnixat.agent_job_csv_plans,'
                         'omnixat.agent_job_expense_plans'],
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
        self.summary_connection = psycopg.connect(self.job_summary_dsn, autocommit=True)
        self.addCleanup(self.summary_connection.close)
        self.clarify_connection = psycopg.connect(self.job_clarify_dsn, autocommit=True)
        self.addCleanup(self.clarify_connection.close)
        self.expense_connection = psycopg.connect(self.job_expense_dsn, autocommit=True)
        self.addCleanup(self.expense_connection.close)
        self.expense_summary_connection = psycopg.connect(self.job_expense_summary_dsn, autocommit=True)
        self.addCleanup(self.expense_summary_connection.close)
        self.journal_plan_connection = psycopg.connect(self.job_journal_plan_dsn, autocommit=True)
        self.addCleanup(self.journal_plan_connection.close)
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

    def csv_plan(self):
        return CSVExtractionPlan((AmountCell('gross', 1, 2), AmountCell('net', 2, 2)))

    def test_saved_csv_plan_survives_restart_reclaim_and_retains_first_actor(self):
        token, job, plan = self.token(), self.create(), self.csv_plan()
        lease = self.jobs.claim(token, self.a, job)
        receipt = self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        self.assertEqual(receipt.plan, plan)
        self.assertEqual(receipt.created_by, str(self.user))
        self.assertEqual(self.jobs.get(token, self.a, job)['checkpoint'], {})
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
        other = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'plan-recovery','agent')", (other, self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.a, other))
        current_token = self.token(sub='plan-recovery')
        with psycopg.connect(self.job_auth_dsn, autocommit=True) as auth, psycopg.connect(self.job_data_dsn, autocommit=True) as data:
            recovered = AuthenticatedJobStore(auth, data, self.verifier)
            current_lease = recovered.claim(current_token, self.a, job)
            self.assertEqual(recovered.get_csv_plan(current_token, self.a, job), receipt)
            self.assertEqual(recovered.save_csv_plan(current_token, self.a, job, current_lease, plan), receipt)
            recovered.cancel(current_token, self.a, job)
        self.assertEqual(self.jobs.get_csv_plan(token, self.a, job), receipt)
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(current_token, self.a, job, current_lease, plan)

    def test_saved_csv_plan_concurrent_retries_and_competing_plans(self):
        token, plan = self.token(), self.csv_plan()
        for same in [True, False]:
            job = self.jobs.create_evidence_task(token, self.a, 'plan-race-' + str(same), self.task)
            lease = self.jobs.claim(token, self.a, job)
            start = Barrier(2)
            def save(index):
                candidate = plan if same or index == 0 else CSVExtractionPlan((AmountCell('gross', 3, 2),))
                with psycopg.connect(self.job_auth_dsn, autocommit=True) as auth, psycopg.connect(self.job_data_dsn, autocommit=True) as data:
                    jobs = AuthenticatedJobStore(auth, data, self.verifier)
                    start.wait(timeout=5)
                    try:
                        return jobs.save_csv_plan(token, self.a, job, lease, candidate)
                    except CreationConflict:
                        return None
            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(save, range(2)))
            if same:
                self.assertEqual(outcomes[0], outcomes[1])
            else:
                self.assertEqual(sum(outcome is not None for outcome in outcomes), 1)
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_csv_plans WHERE job_id=%s', (job,)).fetchone(), (1,))

    def test_csv_plan_validation_rejects_unbounded_or_content_bearing_inputs(self):
        for cells in [[], (), (AmountCell('gross', True, 2),), (AmountCell('gross', 5001, 2),),
                      (AmountCell('gross', 1, 65),), (AmountCell('unsafe prompt', 1, 1),),
                      (AmountCell('gross', 1, 1), AmountCell('gross', 2, 2)),
                      tuple(AmountCell('field_'+str(index), 1, 1) for index in range(33))]:
            with self.subTest(cells_kind=type(cells).__name__), self.assertRaises(ValueError):
                CSVExtractionPlan(cells)
        with self.assertRaises(ValueError):
            CSVExtractionPlan.from_payload([{'field_name': 'gross', 'row': 1, 'column': 1, 'body': 'not plan data'}])
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, job, lease, {'text': 'not plan data'})
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_csv_plans WHERE tenant_id=%s', (self.a,)).fetchone(), (0,))

    def test_saved_csv_plan_checks_current_scopes_membership_and_tenant(self):
        token, job, plan = self.token(), self.create(), self.csv_plan()
        lease = self.jobs.claim(token, self.a, job)
        receipt = self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        for limited in [self.token(scope='records:read'), self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.jobs.save_csv_plan(limited, self.a, job, lease, plan)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s", (self.user,))
        self.assertEqual(self.jobs.get_csv_plan(token, self.a, job), receipt)
        with self.assertRaises(PermissionError):
            self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s', (self.user,))
        for call in [lambda: self.jobs.get_csv_plan(token, self.a, job),
                     lambda: self.jobs.save_csv_plan(token, self.a, job, lease, plan)]:
            with self.assertRaises(AuthenticationError):
                call()
        self.owner.execute("UPDATE omnixat.memberships SET revoked_at=NULL,role='editor' WHERE user_id=%s", (self.user,))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.b, self.user))
        with self.assertRaises(KeyError):
            self.jobs.get_csv_plan(token, self.b, job)
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.b, job, lease, plan)
        self.assertEqual(self.jobs.get_csv_plan(token, self.a, job), receipt)

    def test_csv_plan_requires_running_current_worker_and_rejects_terminal_or_stale_leases(self):
        token, job, plan = self.token(), self.create(), self.csv_plan()
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, job, str(uuid4()), plan)
        first = self.jobs.claim(token, self.a, job)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, job, first, plan)
        current = self.jobs.claim(token, self.a, job)
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, job, first, plan)
        # Even another valid member cannot save using this worker's lease.
        other = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'other-plan-worker','agent')", (other, self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.a, other))
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(self.token(sub='other-plan-worker'), self.a, job, current, plan)
        self.jobs.checkpoint(token, self.a, job, current, {}, complete=True)
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, job, current, plan)

    def test_csv_plan_requires_csv_task_and_does_not_retrofit_hash_only_jobs(self):
        token, plan = self.token(), self.csv_plan()
        actor = self.jobs._actor(token, self.a, write=True)
        legacy = self.jobs._jobs.create(actor, self.a, 'legacy-plan', {'reference': 'fictional'})
        lease = self.jobs.claim(token, self.a, legacy)
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, legacy, lease, plan)
        job = self.create(token)
        lease = self.jobs.claim(token, self.a, job)
        self.owner.execute("UPDATE omnixat.evidence_registrations SET media_type='application/pdf' WHERE tenant_id=%s AND id=%s",
                           (self.a, self.task.evidence_id))
        with self.assertRaises(ValueError):
            self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_csv_plans WHERE tenant_id=%s', (self.a,)).fetchone(), (0,))

    def test_csv_plan_insert_rolls_back_on_failure_and_lease_expiry_before_return(self):
        from omnixat_core import job_csv_plans_postgres
        token, job, plan = self.token(), self.create(), self.csv_plan()
        lease = self.jobs.claim(token, self.a, job, lease_seconds=1)
        with patch.object(job_csv_plans_postgres, '_receipt', side_effect=RuntimeError('fictional interruption')):
            with self.assertRaises(RuntimeError):
                self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        original = job_csv_plans_postgres._receipt
        def after_expiry(*args):
            receipt = original(*args)
            self.job_connection.execute('SELECT pg_sleep(1.1)')
            return receipt
        with patch.object(job_csv_plans_postgres, '_receipt', side_effect=after_expiry):
            with self.assertRaises(ValueError):
                self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_csv_plans WHERE job_id=%s', (job,)).fetchone(), (0,))
        lease = self.jobs.claim(token, self.a, job)
        self.jobs.save_csv_plan(token, self.a, job, lease, plan)

    def test_csv_plan_database_scope_immutability_constraints_and_digest_validation(self):
        token, job, plan = self.token(), self.create(), self.csv_plan()
        lease = self.jobs.claim(token, self.a, job)
        self.jobs.save_csv_plan(token, self.a, job, lease, plan)
        self.assertEqual(self.job_connection.execute('SELECT count(*) FROM omnixat.agent_job_csv_plans').fetchone(), (0,))
        for statement in ['UPDATE omnixat.agent_job_csv_plans SET format_version=1', 'DELETE FROM omnixat.agent_job_csv_plans']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.job_connection.execute(statement)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute("UPDATE omnixat.agent_job_csv_plans SET selections='[]'::jsonb WHERE job_id=%s", (job,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.owner.execute('UPDATE omnixat.agent_job_csv_plans SET format_version=2 WHERE job_id=%s', (job,))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_csv_plans SET tenant_id=%s WHERE job_id=%s', (self.b, job))
        self.owner.execute('UPDATE omnixat.agent_job_csv_plans SET plan_digest=%s WHERE job_id=%s', (b'x'*32, job))
        with self.assertRaises(CreationConflict):
            self.jobs.get_csv_plan(token, self.a, job)
        with self.assertRaises(CreationConflict):
            self.jobs.save_csv_plan(token, self.a, job, lease, plan)


    def csv_execution(self):
        self.admitted_source()
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token, self.a, job)
        self.jobs.save_csv_plan(token, self.a, job, lease, self.csv_plan())
        return token, job, lease

    def execute_csv(self, token, job, lease):
        return execute_preparation_csv(self.jobs, self.gate_connection, token, self.a, job, lease)

    def assert_no_csv_effect(self, job):
        for table in ['csv_extraction_results', 'agent_job_csv_effects']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.' + table + ' WHERE job_id=%s', (job,)).fetchone(), (0,))

    def test_csv_execution_preserves_decimal_provenance_and_replays_after_worker_recovery(self):
        token, job, lease = self.csv_execution()
        self.jobs.checkpoint(token, self.a, job, lease, {'step': 'other-progress'})
        first = self.execute_csv(token, job, lease)
        self.assertEqual(first.created_by, str(self.user))
        self.assertEqual(self.execute_csv(token, job, lease), first)
        amounts, digest = self.owner.execute('SELECT amounts,content_sha256 FROM omnixat.csv_extraction_results WHERE job_id=%s', (job,)).fetchone()
        self.assertEqual(amounts, [{'field_name':'gross','row':1,'column':2,'status':'found','amount':'12.34'},
                                   {'field_name':'net','row':2,'column':2,'status':'missing','amount':None}])
        self.assertEqual(digest, self.task.content_sha256)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
        second_user = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'csv-recovery','agent')", (second_user,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')", (self.a,second_user))
        with psycopg.connect(self.job_auth_dsn, autocommit=True) as auth, psycopg.connect(self.job_data_dsn, autocommit=True) as data:
            recovered = AuthenticatedJobStore(auth,data,self.verifier)
            token2 = self.token(sub='csv-recovery')
            lease2 = recovered.claim(token2,self.a,job)
            self.assertEqual(execute_preparation_csv(recovered,self.gate_connection,token2,self.a,job,lease2),first)
        self.assertEqual(self.jobs.get(token,self.a,job)['checkpoint'], {'step':'other-progress'})
        self.assertEqual(self.jobs.get(token,self.a,job)['status'], 'running')
        self.assertNotIn('12.34', repr(first))

    def test_csv_execution_rechecks_authority_after_read_and_stops_before_effect(self):
        from omnixat_core import preparation_postgres
        token, job, lease = self.csv_execution()
        original = preparation_postgres.read_evidence_for_extraction
        def revoked(*args):
            result = original(*args)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s', (self.user,))
            return result
        with patch.object(preparation_postgres,'read_evidence_for_extraction',side_effect=revoked):
            with self.assertRaises(AuthenticationError):
                self.execute_csv(token,job,lease)
        self.assert_no_csv_effect(job)

    def test_csv_execution_rejects_cancellation_expiry_and_reclaim_during_read(self):
        from omnixat_core import preparation_postgres
        original = preparation_postgres.read_evidence_for_extraction
        for mode in ['cancel','expire','reclaim']:
            with self.subTest(mode=mode):
                # Each task uses a fresh request key and the same pinned original.
                if mode == 'cancel':
                    token, job, lease = self.csv_execution()
                else:
                    job = self.jobs.create_evidence_task(token,self.a,'csv-'+mode,self.task)
                    lease = self.jobs.claim(token,self.a,job)
                    self.jobs.save_csv_plan(token,self.a,job,lease,self.csv_plan())
                def changed(*args):
                    result = original(*args)
                    if mode == 'cancel':
                        self.jobs.cancel(token,self.a,job)
                    else:
                        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job,))
                        if mode == 'reclaim':
                            self.jobs.claim(token,self.a,job)
                    return result
                with patch.object(preparation_postgres,'read_evidence_for_extraction',side_effect=changed):
                    with self.assertRaises(ValueError):
                        self.execute_csv(token,job,lease)
                self.assert_no_csv_effect(job)

    def test_csv_execution_rechecks_scan_gate_at_write_and_on_receipt_replay(self):
        from omnixat_core import preparation_postgres
        token, job, lease = self.csv_execution()
        original = preparation_postgres.read_evidence_for_extraction
        def disabled(*args):
            result = original(*args)
            self.owner.execute('DELETE FROM omnixat_extraction.active_scan_policy')
            return result
        with patch.object(preparation_postgres,'read_evidence_for_extraction',side_effect=disabled):
            with self.assertRaises(ValueError):
                self.execute_csv(token,job,lease)
        self.assert_no_csv_effect(job)
        self.owner.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
        first = self.execute_csv(token,job,lease)
        self.owner.execute('DELETE FROM omnixat_extraction.active_scan_policy')
        with self.assertRaises(EvidenceNotEligible):
            self.execute_csv(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT created_at FROM omnixat.agent_job_csv_effects WHERE job_id=%s',(job,)).fetchone(), (first.created_at,))

    def test_csv_effect_rolls_back_result_and_receipt_on_deadline_or_real_lease_expiry(self):
        token, job, lease = self.csv_execution()
        from omnixat_core.evidence_extraction_postgres import extract_csv_amounts
        result = extract_csv_amounts(self.gate_connection,self.a,self.org,self.task.evidence_id,self.csv_plan().selections)
        with patch('omnixat_core.postgres.monotonic', side_effect=(0,0,0,11)):
            with self.assertRaises(TimeoutError):
                self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,self.csv_plan(),result)
        self.assert_no_csv_effect(job)
        # Delay inside the result insertion so the SQL post-write lease check must roll it back.
        self.owner.execute("""CREATE FUNCTION public.slow_csv_effect() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_sleep(1.1); RETURN NEW; END $$""")
        self.owner.execute('CREATE TRIGGER slow_csv BEFORE INSERT ON omnixat.csv_extraction_results FOR EACH ROW EXECUTE FUNCTION public.slow_csv_effect()')
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()+interval '1 second' WHERE id=%s", (job,))
        try:
            with self.assertRaises(ValueError):
                self.execute_csv(token,job,lease)
        finally:
            self.owner.execute('DROP TRIGGER slow_csv ON omnixat.csv_extraction_results')
            self.owner.execute('DROP FUNCTION public.slow_csv_effect()')
        self.assert_no_csv_effect(job)

    def test_csv_effect_rejects_changed_saved_plan_and_wrong_source(self):
        from omnixat_core import preparation_postgres
        from omnixat_core.evidence_extraction_postgres import extract_csv_amounts
        token, job, lease = self.csv_execution()
        result = extract_csv_amounts(self.gate_connection,self.a,self.org,self.task.evidence_id,self.csv_plan().selections)
        changed = CSVExtractionPlan((AmountCell('other',1,2),))
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,changed,result)
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,self.csv_plan(),replace(result,content_sha256='ff'*32))
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,self.csv_plan(),replace(result,evidence_id=uuid4()))
        original = preparation_postgres.read_evidence_for_extraction
        def wrong(*args):
            return replace(original(*args),evidence_id=uuid4())
        with patch.object(preparation_postgres,'read_evidence_for_extraction',side_effect=wrong):
            with self.assertRaises(EvidenceNotEligible):
                self.execute_csv(token,job,lease)
        self.assert_no_csv_effect(job)

    def test_csv_effect_exec_only_grants_and_concurrent_retry_receipts(self):
        token, job, lease = self.csv_execution()
        start = Barrier(2)
        def execute(_):
            with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data, psycopg.connect(self.job_gate_dsn,autocommit=True) as gate:
                start.wait(timeout=5)
                return execute_preparation_csv(AuthenticatedJobStore(auth,data,self.verifier),gate,token,self.a,job,lease)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second = list(pool.map(execute,range(2)))
        self.assertEqual(first,second)
        for table in ['agent_job_csv_effects','csv_extraction_results','agent_jobs']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.gate_connection.execute('SELECT * FROM omnixat.'+table)
        with self.assertRaises(PermissionError):
            execute_preparation_csv(self.jobs,self.owner,token,self.a,job,lease)
        self.assertEqual(self.gate_connection.execute("SELECT NULLIF(current_setting('omnixat.tenant_id',true),'')").fetchone(), (None,))

    def test_csv_effect_replays_require_current_scope_worker_and_tenant(self):
        from omnixat_core.evidence_extraction_postgres import extract_csv_amounts
        token, job, lease = self.csv_execution()
        result = extract_csv_amounts(self.gate_connection,self.a,self.org,self.task.evidence_id,self.csv_plan().selections)
        for invalid in [self.token(scope='records:read'), self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.jobs.store_csv_effect(self.gate_connection,invalid,self.a,job,lease,self.csv_plan(),result)
        with self.assertRaises(AuthenticationError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.b,job,lease,self.csv_plan(),result)
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,uuid4(),self.csv_plan(),result)
        self.assert_no_csv_effect(job)
        first = self.execute_csv(token,job,lease)
        self.jobs.cancel(token,self.a,job)
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,self.csv_plan(),result)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        with self.assertRaises(AuthenticationError):
            self.execute_csv(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT created_at FROM omnixat.agent_job_csv_effects WHERE job_id=%s',(job,)).fetchone(), (first.created_at,))

    def test_csv_effect_conflicting_result_preserves_original_and_corrupt_plan_is_rejected(self):
        from decimal import Decimal
        from omnixat_core.evidence_extraction_postgres import extract_csv_amounts
        token, job, lease = self.csv_execution()
        result = extract_csv_amounts(self.gate_connection,self.a,self.org,self.task.evidence_id,self.csv_plan().selections)
        first = self.execute_csv(token,job,lease)
        changed = replace(result,amounts=(replace(result.amounts[0],amount=Decimal('99.99')),result.amounts[1]))
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,self.csv_plan(),changed)
        self.assertEqual(self.execute_csv(token,job,lease),first)
        self.owner.execute('UPDATE omnixat.agent_job_csv_plans SET plan_digest=%s WHERE job_id=%s',(b'x'*32,job))
        with self.assertRaises(ValueError):
            self.jobs.store_csv_effect(self.gate_connection,token,self.a,job,lease,self.csv_plan(),result)
        with self.assertRaises(CreationConflict):
            self.execute_csv(token,job,lease)

    def test_csv_effect_receipt_insert_failure_rolls_back_new_result(self):
        token, job, lease = self.csv_execution()
        self.owner.execute("""CREATE FUNCTION public.reject_csv_effect() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'fictional receipt interruption'; END $$""")
        self.owner.execute('CREATE TRIGGER reject_csv BEFORE INSERT ON omnixat.agent_job_csv_effects FOR EACH ROW EXECUTE FUNCTION public.reject_csv_effect()')
        try:
            with self.assertRaises(psycopg.errors.RaiseException):
                self.execute_csv(token,job,lease)
        finally:
            self.owner.execute('DROP TRIGGER reject_csv ON omnixat.agent_job_csv_effects')
            self.owner.execute('DROP FUNCTION public.reject_csv_effect()')
        self.assert_no_csv_effect(job)
        self.execute_csv(token,job,lease)


    def summary(self, token, job, lease):
        return self.jobs.get_csv_summary(self.summary_connection, token, self.a, job, lease)

    def test_csv_summary_recovers_receipt_and_only_unanswered_questions_after_reconnect(self):
        from dataclasses import asdict
        from omnixat_core.access import Principal
        from omnixat_core.evidence_review_postgres import store_csv_clarification
        token, job, lease = self.csv_execution()
        receipt = self.execute_csv(token,job,lease)
        first = self.summary(token,job,lease)
        self.assertEqual(first.receipt,receipt)
        self.assertEqual((first.organisation_id,first.evidence_id,first.content_sha256),
                         (self.org,self.task.evidence_id,self.task.content_sha256.hex()))
        self.assertEqual((first.found_count,first.answered_count,first.unavailable_count),(1,0,0))
        self.assertEqual([(q.cell.field_name,q.reason) for q in first.clarifications],[('net','missing')])
        self.assertNotIn('12.34',str(asdict(first)))
        human = Principal('fictional-human',self.a,'editor')
        store_csv_clarification(self.clarify_connection,human,self.a,self.org,self.task.evidence_id,job,
                               self.csv_plan().selections[1],amount='7.00')
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data:
            recovered = AuthenticatedJobStore(auth,data,self.verifier)
            new = recovered.claim(token,self.a,job)
            summary = recovered.get_csv_summary(self.summary_connection,token,self.a,job,new)
        self.assertEqual(summary.receipt,receipt)
        self.assertEqual((summary.found_count,summary.answered_count,summary.unavailable_count),(1,1,0))
        self.assertEqual(summary.clarifications,())
        self.assertNotIn('7.00',str(asdict(summary)))
        self.assertEqual(self.jobs.get(token,self.a,job)['checkpoint'],{})
        self.assertEqual(self.jobs.get(token,self.a,job)['status'],'running')

    def test_csv_summary_unavailable_human_answer_is_distinct_from_found_or_pending(self):
        from omnixat_core.access import Principal
        from omnixat_core.evidence_review_postgres import store_csv_clarification
        token, job, lease = self.csv_execution()
        self.execute_csv(token,job,lease)
        store_csv_clarification(self.clarify_connection,Principal('fictional-human',self.a,'editor'),
                               self.a,self.org,self.task.evidence_id,job,self.csv_plan().selections[1],amount=None)
        summary = self.summary(token,job,lease)
        self.assertEqual((summary.found_count,summary.answered_count,summary.unavailable_count),(1,1,1))
        self.assertEqual(summary.clarifications,())
        with self.assertRaises(PermissionError):
            store_csv_clarification(self.clarify_connection,self.jobs._actor(token,self.a),
                                   self.a,self.org,self.task.evidence_id,job,self.csv_plan().selections[1],amount=None)

    def test_csv_summary_requires_effect_receipt_and_current_scan_eligibility(self):
        token, job, lease = self.csv_execution()
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)
        self.execute_csv(token,job,lease)
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'")
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v1'")
        self.summary(token,job,lease)
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
            (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
            VALUES (%s,%s,%s,%s,'fictional-v1','blocked')""",
            (self.a,self.task.evidence_id,self.task.content_sha256,len(self.original)))
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)

    def test_csv_summary_rejects_revoked_downgraded_wrong_scope_and_other_tenant(self):
        token, job, lease = self.csv_execution()
        self.execute_csv(token,job,lease)
        for invalid in [self.token(scope='records:read'),self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.summary(invalid,job,lease)
        with self.assertRaises(AuthenticationError):
            self.jobs.get_csv_summary(self.summary_connection,token,self.b,job,lease)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        with self.assertRaises(PermissionError):
            self.summary(token,job,lease)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor',revoked_at=now() WHERE user_id=%s",(self.user,))
        with self.assertRaises(AuthenticationError):
            self.summary(token,job,lease)

    def test_csv_summary_rejects_wrong_worker_expired_reclaimed_and_cancelled_job(self):
        token, job, lease = self.csv_execution()
        self.execute_csv(token,job,lease)
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,uuid4())
        second = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'summary-worker','agent')",(second,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.a,second))
        second_token = self.token(sub='summary-worker')
        with self.assertRaises(EvidenceNotEligible):
            self.summary(second_token,job,lease)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)
        new = self.jobs.claim(second_token,self.a,job)
        self.summary(second_token,job,new)
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)
        self.jobs.cancel(token,self.a,job)
        with self.assertRaises(EvidenceNotEligible):
            self.summary(second_token,job,new)

    def test_csv_summary_exec_only_role_cannot_read_values_or_mutate_and_cleans_context(self):
        token, job, lease = self.csv_execution()
        self.execute_csv(token,job,lease)
        self.summary(token,job,lease)
        for table in ['evidence_quarantine','csv_extraction_results','csv_clarification_answers','agent_job_csv_effects']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.summary_connection.execute('SELECT * FROM omnixat.'+table)
        for function in ["read_eligible_original(NULL,NULL)","read_csv_review(NULL,NULL,NULL)",
                         "read_csv_review_with_answers(NULL,NULL,NULL)",
                         "store_csv_answer(NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)"]:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.summary_connection.execute('SELECT * FROM omnixat_extraction.'+function)
        for connection in [self.owner,self.gate_connection]:
            with self.assertRaises(PermissionError):
                self.jobs.get_csv_summary(connection,token,self.a,job,lease)
        self.assertEqual(self.summary_connection.execute("SELECT NULLIF(current_setting('omnixat.tenant_id',true),'')").fetchone(),(None,))

    def test_csv_summary_rejects_changed_plan_source_and_corrupt_results_or_answers(self):
        from psycopg.types.json import Jsonb
        token, job, lease = self.csv_execution()
        self.execute_csv(token,job,lease)
        saved = self.owner.execute('SELECT amounts FROM omnixat.csv_extraction_results WHERE job_id=%s',(job,)).fetchone()[0]
        for changed in [[saved[1],saved[0]], [dict(saved[0],amount='not-a-decimal'),saved[1]],
                        [dict(saved[0],status='unknown'),saved[1]], [dict(saved[0],extra='secret'),saved[1]]]:
            self.owner.execute('UPDATE omnixat.csv_extraction_results SET amounts=%s WHERE job_id=%s',(Jsonb(changed),job))
            with self.assertRaises(EvidenceNotEligible):
                self.summary(token,job,lease)
        self.owner.execute('UPDATE omnixat.csv_extraction_results SET amounts=%s WHERE job_id=%s',(Jsonb(saved),job))
        self.owner.execute("""INSERT INTO omnixat.csv_clarification_answers
            (tenant_id,job_id,field_name,source_row,source_column,amount,answered_by)
            VALUES (%s,%s,'net',3,2,'7.00','fictional-human')""",(self.a,job))
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)
        self.owner.execute('DELETE FROM omnixat.csv_clarification_answers WHERE job_id=%s',(job,))
        self.owner.execute('UPDATE omnixat.agent_job_csv_plans SET plan_digest=%s WHERE job_id=%s',(b'x'*32,job))
        with self.assertRaises(CreationConflict):
            self.summary(token,job,lease)


    def test_csv_summary_database_output_contains_only_metadata_and_read_only_transaction(self):
        from omnixat_core.job_csv_plans_postgres import _digest
        from omnixat_core.postgres import _tenant_transaction
        from uuid import UUID
        token, job, lease = self.csv_execution()
        self.execute_csv(token,job,lease)
        with _tenant_transaction(self.summary_connection,UUID(self.a),tables_required=('agent_jobs',)):
            self.assertEqual(self.summary_connection.execute('SHOW transaction_read_only').fetchone(),('on',))
            row = self.summary_connection.execute('SELECT * FROM omnixat_extraction.read_job_csv_summary(%s,%s,%s,%s)',
                (job,str(self.user),lease,_digest(self.csv_plan()))).fetchone()
            cells = row[-1]
            self.assertEqual([set(cell) for cell in cells],[{'field_name','row','column','status','answered','unavailable'}]*2)
            self.assertNotIn('12.34',str(row))
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_claims
            (tenant_id,evidence_id,policy_version,lease_token,expires_at)
            VALUES (%s,%s,'fictional-v1',%s,clock_timestamp()+interval '60 seconds')""",(self.a,self.task.evidence_id,uuid4()))
        with self.assertRaises(EvidenceNotEligible):
            self.summary(token,job,lease)


    def expense_plan_setup(self):
        from datetime import date
        from omnixat_core.expense_context import ExpenseDraftContext
        token, job = self.token(), self.create()
        lease = self.jobs.claim(token,self.a,job)
        self.jobs.save_csv_plan(token,self.a,job,lease,self.csv_plan())
        period, account = uuid4(),uuid4()
        self.owner.execute("""INSERT INTO omnixat.expense_accounting_periods
            (tenant_id,organisation_id,id,starts_on,ends_on,open_for_drafts)
            VALUES (%s,%s,%s,'2026-01-01','2026-12-31',true)""",(self.a,self.org,period))
        self.owner.execute("""INSERT INTO omnixat.expense_account_policy
            (tenant_id,organisation_id,account_id,eligible_for_drafts) VALUES (%s,%s,%s,true)""",(self.a,self.org,account))
        plan = ExpensePreparationPlan(self.csv_plan().selections[0],ExpenseDraftContext('GBP',date(2026,11,7),account),period)
        return token,job,lease,plan

    def test_expense_plan_survives_restart_and_reclaim_with_original_attribution(self):
        token,job,lease,plan = self.expense_plan_setup()
        first = self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        self.assertEqual(first.plan,plan)
        self.assertEqual(first.created_by,str(self.user))
        self.assertEqual(self.jobs.save_expense_plan(token,self.a,job,lease,plan),first)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        second = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'expense-recovery','agent')",(second,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.a,second))
        with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data:
            restored = AuthenticatedJobStore(auth,data,self.verifier)
            token2 = self.token(sub='expense-recovery')
            new = restored.claim(token2,self.a,job)
            self.assertEqual(restored.get_expense_plan(token2,self.a,job),first)
            self.assertEqual(restored.save_expense_plan(token2,self.a,job,new,plan),first)
        self.assertEqual(self.jobs.get(token,self.a,job)['checkpoint'],{})
        for table in ['csv_expense_drafts','evidence_draft_amounts','agent_job_csv_effects']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.'+table+' WHERE tenant_id=%s',(self.a,)).fetchone(),(0,))

    def test_expense_plan_requires_exact_saved_cell_and_current_period_account_configuration(self):
        from datetime import date
        token,job,lease,plan = self.expense_plan_setup()
        invalid = [replace(plan,source_cell=AmountCell('gross',1,1)),
                   replace(plan,context=replace(plan.context,accounting_date=date(2027,1,1))),
                   replace(plan,period_id=uuid4()),
                   replace(plan,context=replace(plan.context,expense_account_id=uuid4()))]
        for item in invalid:
            with self.assertRaises(ValueError):
                self.jobs.save_expense_plan(token,self.a,job,lease,item)
        first = self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        for table,flag in [('expense_accounting_periods','open_for_drafts'),('expense_account_policy','eligible_for_drafts')]:
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=false WHERE tenant_id=%s',(self.a,))
            with self.assertRaises(ValueError):
                self.jobs.save_expense_plan(token,self.a,job,lease,plan)
            # Historical references remain readable; they confer no current eligibility.
            self.assertEqual(self.jobs.get_expense_plan(token,self.a,job),first)
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=true WHERE tenant_id=%s',(self.a,))

    def test_expense_plan_concurrent_same_and_competing_inputs_preserve_one_receipt(self):
        from datetime import date
        token,job,lease,plan = self.expense_plan_setup()
        start = Barrier(2)
        def save(item):
            with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data:
                start.wait(timeout=5)
                try:
                    return AuthenticatedJobStore(auth,data,self.verifier).save_expense_plan(token,self.a,job,lease,item)
                except CreationConflict:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second = list(pool.map(save,[plan,plan]))
        self.assertEqual(first,second)
        start = Barrier(2)
        changed = replace(plan,context=replace(plan.context,accounting_date=date(2026,11,8)))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save,[plan,changed]))
        self.assertEqual(results,[first,None])
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_expense_plans WHERE job_id=%s',(job,)).fetchone(),(1,))
        # Competing first writers on a fresh task also produce exactly one winner.
        job = self.jobs.create_evidence_task(token,self.a,'expense-plan-race',self.task)
        lease = self.jobs.claim(token,self.a,job)
        self.jobs.save_csv_plan(token,self.a,job,lease,self.csv_plan())
        start = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save,[plan,changed]))
        self.assertEqual(sum(result is not None for result in results),1)
        winner = next(result for result in results if result is not None)
        self.assertEqual(self.jobs.get_expense_plan(token,self.a,job),winner)

    def test_expense_plan_current_scope_role_revocation_and_tenant_boundary(self):
        token,job,lease,plan = self.expense_plan_setup()
        for invalid in [self.token(scope='records:read'),self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.jobs.save_expense_plan(invalid,self.a,job,lease,plan)
        receipt = self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        with self.assertRaises(AuthenticationError):
            self.jobs.get_expense_plan(token,self.b,job)
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.b,self.user))
        with self.assertRaises(KeyError):
            self.jobs.get_expense_plan(token,self.b,job)
        with self.assertRaises(ValueError):
            self.jobs.save_expense_plan(token,self.b,job,lease,plan)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        self.assertEqual(self.jobs.get_expense_plan(token,self.a,job),receipt)
        with self.assertRaises(PermissionError):
            self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        with self.assertRaises(AuthenticationError):
            self.jobs.get_expense_plan(token,self.a,job)

    def test_expense_plan_expired_wrong_worker_and_cancelled_claims_are_rejected(self):
        token,job,lease,plan = self.expense_plan_setup()
        with self.assertRaises(ValueError):
            self.jobs.save_expense_plan(token,self.a,job,uuid4(),plan)
        self.owner.execute("UPDATE omnixat.agent_jobs SET claimed_by='different-worker' WHERE id=%s",(job,))
        with self.assertRaises(ValueError):
            self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        self.owner.execute("UPDATE omnixat.agent_jobs SET claimed_by=%s,lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(str(self.user),job))
        with self.assertRaises(ValueError):
            self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        new = self.jobs.claim(token,self.a,job)
        self.jobs.save_expense_plan(token,self.a,job,new,plan)
        self.jobs.cancel(token,self.a,job)
        with self.assertRaises(ValueError):
            self.jobs.save_expense_plan(token,self.a,job,new,plan)

    def test_expense_plan_rolls_back_on_insert_failure_and_actual_lease_expiry(self):
        from omnixat_core import job_expense_plans_postgres
        token,job,lease,plan = self.expense_plan_setup()
        with patch.object(job_expense_plans_postgres,'_receipt',side_effect=RuntimeError('fictional interruption')):
            with self.assertRaises(RuntimeError):
                self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        original = job_expense_plans_postgres._receipt
        def delayed(*args):
            receipt = original(*args)
            self.job_connection.execute('SELECT pg_sleep(1.1)')
            return receipt
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()+interval '1 second' WHERE id=%s",(job,))
        with patch.object(job_expense_plans_postgres,'_receipt',side_effect=delayed):
            with self.assertRaises(ValueError):
                self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_expense_plans WHERE job_id=%s',(job,)).fetchone(),(0,))
        new = self.jobs.claim(token,self.a,job)
        self.jobs.save_expense_plan(token,self.a,job,new,plan)

    def test_expense_plan_database_immutability_scope_foreign_keys_and_digest(self):
        token,job,lease,plan = self.expense_plan_setup()
        self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        self.assertEqual(self.job_connection.execute('SELECT count(*) FROM omnixat.agent_job_expense_plans').fetchone(),(0,))
        for statement in ['UPDATE omnixat.agent_job_expense_plans SET currency=currency','DELETE FROM omnixat.agent_job_expense_plans']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.job_connection.execute(statement)
        for statement in ["UPDATE omnixat.agent_job_expense_plans SET currency='USD'",'UPDATE omnixat.agent_job_expense_plans SET source_row=0']:
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.owner.execute(statement+' WHERE job_id=%s',(job,))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_expense_plans SET organisation_id=%s WHERE job_id=%s',(uuid4(),job))
        self.owner.execute('UPDATE omnixat.agent_job_expense_plans SET plan_digest=%s WHERE job_id=%s',(b'x'*32,job))
        with self.assertRaises(CreationConflict):
            self.jobs.get_expense_plan(token,self.a,job)
        with self.assertRaises(CreationConflict):
            self.jobs.save_expense_plan(token,self.a,job,lease,plan)

    def test_expense_plan_missing_csv_plan_or_corrupt_parent_is_rejected(self):
        token,job,lease,plan = self.expense_plan_setup()
        other = self.jobs.create_evidence_task(token,self.a,'no-csv-plan',self.task)
        other_lease = self.jobs.claim(token,self.a,other)
        with self.assertRaises(ValueError):
            self.jobs.save_expense_plan(token,self.a,other,other_lease,plan)
        self.owner.execute('UPDATE omnixat.agent_job_csv_plans SET plan_digest=%s WHERE job_id=%s',(b'x'*32,job))
        with self.assertRaises(CreationConflict):
            self.jobs.save_expense_plan(token,self.a,job,lease,plan)


    def expense_execution_setup(self, *, source_cell=None):
        token,job,lease,plan = self.expense_plan_setup()
        if source_cell is not None:
            plan = replace(plan,source_cell=source_cell)
        self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        self.admitted_source()
        self.execute_csv(token,job,lease)
        return token,job,lease,plan

    def execute_expense(self, token, job, lease):
        return self.jobs.execute_expense_plan(self.expense_connection,token,self.a,job,lease)

    def assert_no_expense_effect(self, job):
        for table in ['agent_job_expense_effects','csv_expense_drafts','evidence_draft_amounts']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.'+table+' WHERE job_id=%s',(job,)).fetchone(),(0,))

    def test_expense_execution_is_atomic_source_backed_and_replays_after_worker_recovery(self):
        from dataclasses import asdict
        token,job,lease,plan = self.expense_execution_setup()
        first = self.execute_expense(token,job,lease)
        self.assertEqual(first.created_by,str(self.user))
        self.assertEqual(self.execute_expense(token,job,lease),first)
        self.assertEqual(self.owner.execute('SELECT amount_pence,created_by,period_id,expense_account_id FROM omnixat.csv_expense_drafts WHERE id=%s',(first.expense_id,)).fetchone(),
                         (1234,str(self.user),plan.period_id,plan.context.expense_account_id))
        self.assertEqual(self.owner.execute('SELECT amount,source_kind,created_by FROM omnixat.evidence_draft_amounts WHERE job_id=%s',(job,)).fetchone(),('12.34','extracted',str(self.user)))
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        second = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'expense-effect-recovery','agent')",(second,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.a,second))
        with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data:
            restored = AuthenticatedJobStore(auth,data,self.verifier)
            second_token = self.token(sub='expense-effect-recovery')
            new = restored.claim(second_token,self.a,job)
            self.assertEqual(restored.execute_expense_plan(self.expense_connection,second_token,self.a,job,new),first)
        self.assertNotIn('amount',str(asdict(first)))
        self.assertEqual(self.jobs.get(token,self.a,job)['checkpoint'],{})
        self.assertEqual(self.jobs.get(token,self.a,job)['status'],'running')
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.expense_journal_drafts WHERE tenant_id=%s',(self.a,)).fetchone(),(0,))

    def test_expense_execution_concurrent_retries_have_one_receipt(self):
        token,job,lease,plan = self.expense_execution_setup()
        start = Barrier(2)
        def execute(_):
            with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data, psycopg.connect(self.job_expense_dsn,autocommit=True) as effect:
                start.wait(timeout=5)
                return AuthenticatedJobStore(auth,data,self.verifier).execute_expense_plan(effect,token,self.a,job,lease)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second = list(pool.map(execute,range(2)))
        self.assertEqual(first,second)
        for table in ['agent_job_expense_effects','csv_expense_drafts','evidence_draft_amounts']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.'+table+' WHERE job_id=%s',(job,)).fetchone(),(1,))

    def test_expense_execution_waits_for_human_answer_and_preserves_clarified_source(self):
        from omnixat_core.access import Principal
        from omnixat_core.evidence_review_postgres import store_csv_clarification
        token,job,lease,plan = self.expense_execution_setup(source_cell=self.csv_plan().selections[1])
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assert_no_expense_effect(job)
        store_csv_clarification(self.clarify_connection,Principal('fictional-human',self.a,'editor'),
            self.a,self.org,self.task.evidence_id,job,plan.source_cell,amount='7.00')
        result = self.execute_expense(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT amount_pence FROM omnixat.csv_expense_drafts WHERE id=%s',(result.expense_id,)).fetchone(),(700,))
        self.assertEqual(self.owner.execute('SELECT source_kind,amount FROM omnixat.evidence_draft_amounts WHERE job_id=%s',(job,)).fetchone(),('clarified','7.00'))

    def test_expense_execution_rejects_unavailable_answer_without_guessing(self):
        from omnixat_core.access import Principal
        from omnixat_core.evidence_review_postgres import store_csv_clarification
        token,job,lease,plan = self.expense_execution_setup(source_cell=self.csv_plan().selections[1])
        store_csv_clarification(self.clarify_connection,Principal('fictional-human',self.a,'editor'),
            self.a,self.org,self.task.evidence_id,job,plan.source_cell,amount=None)
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assert_no_expense_effect(job)

    def test_expense_execution_rejects_nonpositive_and_fractional_pence_and_rolls_back_source(self):
        from psycopg.types.json import Jsonb
        token,job,lease,plan = self.expense_execution_setup()
        original = self.owner.execute('SELECT amounts FROM omnixat.csv_extraction_results WHERE job_id=%s',(job,)).fetchone()[0]
        for value in ['0','-1','1.001']:
            changed = [dict(original[0],amount=value),original[1]]
            self.owner.execute('UPDATE omnixat.csv_extraction_results SET amounts=%s WHERE job_id=%s',(Jsonb(changed),job))
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.execute_expense(token,job,lease)
            self.assert_no_expense_effect(job)
        self.owner.execute('UPDATE omnixat.csv_extraction_results SET amounts=%s WHERE job_id=%s',(Jsonb(original),job))
        self.execute_expense(token,job,lease)

    def test_expense_execution_checks_current_context_and_scan_policy_on_creation_and_retry(self):
        token,job,lease,plan = self.expense_execution_setup()
        for table,flag in [('expense_accounting_periods','open_for_drafts'),('expense_account_policy','eligible_for_drafts')]:
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=false WHERE tenant_id=%s',(self.a,))
            with self.assertRaises(ValueError):
                self.execute_expense(token,job,lease)
            self.assert_no_expense_effect(job)
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=true WHERE tenant_id=%s',(self.a,))
        first = self.execute_expense(token,job,lease)
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'")
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT expense_id FROM omnixat.agent_job_expense_effects WHERE job_id=%s',(job,)).fetchone(),(first.expense_id,))

    def test_expense_execution_scope_revocation_role_tenant_and_wrong_worker_denial(self):
        token,job,lease,plan = self.expense_execution_setup()
        for invalid in [self.token(scope='records:read'),self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.execute_expense(invalid,job,lease)
        with self.assertRaises(AuthenticationError):
            self.jobs.execute_expense_plan(self.expense_connection,token,self.b,job,lease)
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,uuid4())
        self.owner.execute("UPDATE omnixat.agent_jobs SET claimed_by='wrong-worker' WHERE id=%s",(job,))
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.owner.execute("UPDATE omnixat.agent_jobs SET claimed_by=%s WHERE id=%s",(str(self.user),job))
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        with self.assertRaises(PermissionError):
            self.execute_expense(token,job,lease)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor',revoked_at=now() WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        with self.assertRaises(AuthenticationError):
            self.execute_expense(token,job,lease)
        self.assert_no_expense_effect(job)

    def test_expense_execution_expired_claim_and_terminal_replay_are_rejected(self):
        token,job,lease,plan = self.expense_execution_setup()
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assert_no_expense_effect(job)
        new = self.jobs.claim(token,self.a,job)
        first = self.execute_expense(token,job,new)
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.jobs.cancel(token,self.a,job)
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,new)
        self.assertEqual(self.owner.execute('SELECT expense_id FROM omnixat.agent_job_expense_effects WHERE job_id=%s',(job,)).fetchone(),(first.expense_id,))

    def test_expense_execution_receipt_failure_and_real_lease_expiry_roll_back_all_new_rows(self):
        token,job,lease,plan = self.expense_execution_setup()
        self.owner.execute("""CREATE FUNCTION public.reject_expense_effect() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'fictional interruption'; END $$""")
        self.owner.execute('CREATE TRIGGER reject_expense BEFORE INSERT ON omnixat.agent_job_expense_effects FOR EACH ROW EXECUTE FUNCTION public.reject_expense_effect()')
        try:
            with self.assertRaises(psycopg.errors.RaiseException):
                self.execute_expense(token,job,lease)
        finally:
            self.owner.execute('DROP TRIGGER reject_expense ON omnixat.agent_job_expense_effects')
            self.owner.execute('DROP FUNCTION public.reject_expense_effect()')
        self.assert_no_expense_effect(job)
        self.owner.execute("""CREATE FUNCTION public.slow_expense_effect() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_sleep(1.1); RETURN NEW; END $$""")
        self.owner.execute('CREATE TRIGGER slow_expense BEFORE INSERT ON omnixat.csv_expense_drafts FOR EACH ROW EXECUTE FUNCTION public.slow_expense_effect()')
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()+interval '1 second' WHERE id=%s",(job,))
        try:
            with self.assertRaises(ValueError):
                self.execute_expense(token,job,lease)
        finally:
            self.owner.execute('DROP TRIGGER slow_expense ON omnixat.csv_expense_drafts')
            self.owner.execute('DROP FUNCTION public.slow_expense_effect()')
        self.assert_no_expense_effect(job)

    def test_expense_execution_exec_only_grants_and_missing_extraction_effect(self):
        token,job,lease,plan = self.expense_plan_setup()
        self.jobs.save_expense_plan(token,self.a,job,lease,plan)
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assert_no_expense_effect(job)
        self.admitted_source()
        self.execute_csv(token,job,lease)
        self.execute_expense(token,job,lease)
        for table in ['csv_expense_drafts','evidence_draft_amounts','agent_job_expense_effects']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.expense_connection.execute('SELECT * FROM omnixat.'+table)
        for connection in [self.owner,self.gate_connection,self.clarify_connection]:
            with self.assertRaises(PermissionError):
                self.jobs.execute_expense_plan(connection,token,self.a,job,lease)
        self.assertEqual(self.expense_connection.execute("SELECT NULLIF(current_setting('omnixat.tenant_id',true),'')").fetchone(),(None,))

    def test_expense_execution_preserves_other_actors_preexisting_source_draft(self):
        token,job,lease,plan = self.expense_execution_setup()
        with self.owner.transaction():
            self.owner.execute("SELECT set_config('omnixat.tenant_id',%s,true)",(self.a,))
            self.owner.execute('SELECT * FROM omnixat_extraction.create_csv_draft_amount(%s,%s,%s,%s,%s,%s,%s)',
                (self.org,self.task.evidence_id,job,plan.source_cell.field_name,plan.source_cell.row,plan.source_cell.column,'fictional-other-human'))
        before = self.owner.execute('SELECT * FROM omnixat.evidence_draft_amounts WHERE job_id=%s',(job,)).fetchall()
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT * FROM omnixat.evidence_draft_amounts WHERE job_id=%s',(job,)).fetchall(),before)
        for table in ['agent_job_expense_effects','csv_expense_drafts']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.'+table+' WHERE job_id=%s',(job,)).fetchone(),(0,))

    def test_expense_execution_serializes_with_concurrent_cancellation(self):
        token,job,lease,plan = self.expense_execution_setup()
        start = Barrier(2)
        def operation(cancel):
            with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data, psycopg.connect(self.job_expense_dsn,autocommit=True) as effect:
                jobs = AuthenticatedJobStore(auth,data,self.verifier)
                start.wait(timeout=5)
                if cancel:
                    return jobs.cancel(token,self.a,job)
                try:
                    return jobs.execute_expense_plan(effect,token,self.a,job,lease)
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipt,cancellation = list(pool.map(operation,[False,True]))
        self.assertEqual(self.jobs.get(token,self.a,job)['status'],'cancelled')
        for table in ['agent_job_expense_effects','csv_expense_drafts','evidence_draft_amounts']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.'+table+' WHERE job_id=%s',(job,)).fetchone(),(0 if receipt is None else 1,))


    def test_expense_execution_rechecks_identity_after_input_recovery_and_pins_receipt_digests(self):
        from datetime import date
        from omnixat_core.job_expense_plans_postgres import _digest
        token,job,lease,plan = self.expense_execution_setup()
        original = self.jobs.get_expense_plan
        def revoke_after_plan(*args):
            receipt = original(*args)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
            return receipt
        with patch.object(self.jobs,'get_expense_plan',side_effect=revoke_after_plan):
            with self.assertRaises(AuthenticationError):
                self.execute_expense(token,job,lease)
        self.assert_no_expense_effect(job)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=NULL WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        first = self.execute_expense(token,job,lease)
        # Even an owner-corrupted but internally valid changed intent cannot reuse
        # a receipt for the originally saved inputs.
        changed = replace(plan,context=replace(plan.context,accounting_date=date(2026,11,8)))
        self.owner.execute('UPDATE omnixat.agent_job_expense_plans SET accounting_date=%s,plan_digest=%s WHERE job_id=%s',
                           (changed.context.accounting_date,_digest(changed),job))
        with self.assertRaises(ValueError):
            self.execute_expense(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT accounting_date FROM omnixat.csv_expense_drafts WHERE id=%s',(first.expense_id,)).fetchone(),(plan.context.accounting_date,))
        self.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_extraction.read_job_csv_summary(uuid,text,uuid,bytea) TO {}').format(sql.Identifier(self.job_expense_role)))
        try:
            with self.assertRaises(PermissionError):
                self.jobs.get_csv_summary(self.expense_connection,token,self.a,job,lease)
        finally:
            self.owner.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION omnixat_extraction.read_job_csv_summary(uuid,text,uuid,bytea) FROM {}').format(sql.Identifier(self.job_expense_role)))


    def expense_summary(self, token, job, lease):
        return self.jobs.get_expense_summary(self.expense_summary_connection,token,self.a,job,lease)

    def test_expense_summary_recovers_exact_receipt_and_context_after_worker_restart(self):
        from dataclasses import asdict
        token,job,lease,plan = self.expense_execution_setup()
        receipt = self.execute_expense(token,job,lease)
        first = self.expense_summary(token,job,lease)
        self.assertEqual(first.receipt,receipt)
        self.assertEqual(first.plan,plan)
        self.assertEqual((first.organisation_id,first.evidence_id,first.content_sha256,first.policy_version,first.source_kind),
                         (self.org,self.task.evidence_id,self.task.content_sha256.hex(),'fictional-v1','extracted'))
        self.assertNotIn('12.34',str(asdict(first)))
        before = self.owner.execute('SELECT * FROM omnixat.agent_jobs WHERE id=%s',(job,)).fetchone()
        self.assertEqual(self.expense_summary(token,job,lease),first)
        self.assertEqual(self.owner.execute('SELECT * FROM omnixat.agent_jobs WHERE id=%s',(job,)).fetchone(),before)
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        second = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'expense-summary-recovery','agent')",(second,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.a,second))
        with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data:
            restored = AuthenticatedJobStore(auth,data,self.verifier)
            token2 = self.token(sub='expense-summary-recovery')
            new = restored.claim(token2,self.a,job)
            self.assertEqual(restored.get_expense_summary(self.expense_summary_connection,token2,self.a,job,new),first)

    def test_expense_summary_checks_current_scan_and_bookkeeping_policy(self):
        token,job,lease,plan = self.expense_execution_setup()
        self.execute_expense(token,job,lease)
        for table,flag in [('expense_accounting_periods','open_for_drafts'),('expense_account_policy','eligible_for_drafts')]:
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=false WHERE tenant_id=%s',(self.a,))
            with self.assertRaises(EvidenceNotEligible):
                self.expense_summary(token,job,lease)
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=true WHERE tenant_id=%s',(self.a,))
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'")
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v1'")
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_claims
            (tenant_id,evidence_id,policy_version,lease_token,expires_at)
            VALUES (%s,%s,'fictional-v1',%s,clock_timestamp()+interval '60 seconds')""",(self.a,self.task.evidence_id,uuid4()))
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.owner.execute("""INSERT INTO omnixat.evidence_scan_verdicts
            (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict)
            VALUES (%s,%s,%s,%s,'fictional-v1','blocked')""",
            (self.a,self.task.evidence_id,self.task.content_sha256,len(self.original)))
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)

    def test_expense_summary_scope_revocation_role_and_tenant_boundaries(self):
        token,job,lease,plan = self.expense_execution_setup()
        self.execute_expense(token,job,lease)
        for invalid in [self.token(scope='records:read'),self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.expense_summary(invalid,job,lease)
        with self.assertRaises(AuthenticationError):
            self.jobs.get_expense_summary(self.expense_summary_connection,token,self.b,job,lease)
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.b,self.user))
        with self.assertRaises(KeyError):
            self.jobs.get_expense_summary(self.expense_summary_connection,token,self.b,job,lease)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        with self.assertRaises(PermissionError):
            self.expense_summary(token,job,lease)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        with self.assertRaises(AuthenticationError):
            self.expense_summary(token,job,lease)

    def test_expense_summary_expired_wrong_replaced_and_cancelled_claims_are_rejected(self):
        token,job,lease,plan = self.expense_execution_setup()
        self.execute_expense(token,job,lease)
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,uuid4())
        self.owner.execute("UPDATE omnixat.agent_jobs SET claimed_by='different-worker' WHERE id=%s",(job,))
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        self.owner.execute("UPDATE omnixat.agent_jobs SET claimed_by=%s,lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(str(self.user),job))
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        new = self.jobs.claim(token,self.a,job)
        self.expense_summary(token,job,new)
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        self.jobs.cancel(token,self.a,job)
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,new)

    def test_expense_summary_requires_effect_and_rejects_changed_amount_context_actor_or_digest(self):
        from datetime import date
        token,job,lease,plan = self.expense_execution_setup()
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        receipt = self.execute_expense(token,job,lease)
        for column,value,original in [('amount_pence',1235,1234),
                                      ('accounting_date',date(2026,11,8),plan.context.accounting_date),
                                      ('created_by','fictional-other',str(self.user))]:
            self.owner.execute(sql.SQL('UPDATE omnixat.csv_expense_drafts SET {}=%s WHERE id=%s').format(sql.Identifier(column)),(value,receipt.expense_id))
            with self.assertRaises(EvidenceNotEligible):
                self.expense_summary(token,job,lease)
            self.owner.execute(sql.SQL('UPDATE omnixat.csv_expense_drafts SET {}=%s WHERE id=%s').format(sql.Identifier(column)),(original,receipt.expense_id))
        self.owner.execute('UPDATE omnixat.agent_job_expense_effects SET expense_plan_digest=%s WHERE job_id=%s',(b'x'*32,job))
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)

    def test_expense_summary_metadata_only_database_output_and_dedicated_read_role(self):
        from omnixat_core.job_csv_plans_postgres import _digest as csv_digest
        from omnixat_core.job_expense_plans_postgres import _digest as expense_digest
        from omnixat_core.postgres import _tenant_transaction
        from uuid import UUID
        token,job,lease,plan = self.expense_execution_setup()
        self.execute_expense(token,job,lease)
        with _tenant_transaction(self.expense_summary_connection,UUID(self.a),tables_required=('agent_jobs',)):
            self.assertEqual(self.expense_summary_connection.execute('SHOW transaction_read_only').fetchone(),('on',))
            cursor = self.expense_summary_connection.execute('SELECT * FROM omnixat_extraction.read_job_expense_summary(%s,%s,%s,%s,%s)',
                (job,str(self.user),lease,csv_digest(self.csv_plan()),expense_digest(plan)))
            self.assertEqual({column.name for column in cursor.description},
                {'expense_id','created_by','created_at','expense_created_at','organisation_id','evidence_id','content_sha256','policy_version','source_kind'})
            self.assertNotIn('12.34',str(cursor.fetchone()))
        for table in ['csv_expense_drafts','evidence_draft_amounts','agent_job_expense_effects']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.expense_summary_connection.execute('SELECT * FROM omnixat.'+table)
        for function in ['read_csv_expense_draft(NULL,NULL)','read_eligible_original(NULL,NULL)',
                         'create_job_expense_draft(NULL,NULL,NULL,NULL,NULL)']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.expense_summary_connection.execute('SELECT * FROM omnixat_extraction.'+function)
        for connection in [self.owner,self.expense_connection,self.gate_connection]:
            with self.assertRaises(PermissionError):
                self.jobs.get_expense_summary(connection,token,self.a,job,lease)
        self.assertEqual(self.expense_summary_connection.execute("SELECT NULLIF(current_setting('omnixat.tenant_id',true),'')").fetchone(),(None,))

    def test_expense_summary_clarified_source_and_fresh_identity_after_plan_recovery(self):
        from omnixat_core.access import Principal
        from omnixat_core.evidence_review_postgres import store_csv_clarification
        token,job,lease,plan = self.expense_execution_setup(source_cell=self.csv_plan().selections[1])
        store_csv_clarification(self.clarify_connection,Principal('fictional-human',self.a,'editor'),
            self.a,self.org,self.task.evidence_id,job,plan.source_cell,amount='7.00')
        receipt = self.execute_expense(token,job,lease)
        self.assertEqual(self.expense_summary(token,job,lease).source_kind,'clarified')
        original = self.jobs.get_expense_plan
        def revoke_after_plan(*args):
            saved = original(*args)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
            return saved
        with patch.object(self.jobs,'get_expense_plan',side_effect=revoke_after_plan):
            with self.assertRaises(AuthenticationError):
                self.expense_summary(token,job,lease)
        self.assertEqual(self.owner.execute('SELECT expense_id FROM omnixat.agent_job_expense_effects WHERE job_id=%s',(job,)).fetchone(),(receipt.expense_id,))

    def test_expense_summary_rejects_receipt_linked_to_another_jobs_draft(self):
        token,job,lease,plan = self.expense_execution_setup()
        first = self.execute_expense(token,job,lease)
        second_job = self.jobs.create_evidence_task(token,self.a,'expense-summary-other-job',self.task)
        second_lease = self.jobs.claim(token,self.a,second_job)
        self.jobs.save_csv_plan(token,self.a,second_job,second_lease,self.csv_plan())
        self.jobs.save_expense_plan(token,self.a,second_job,second_lease,plan)
        self.execute_csv(token,second_job,second_lease)
        with self.owner.transaction():
            self.owner.execute("SELECT set_config('omnixat.tenant_id',%s,true)",(self.a,))
            self.owner.execute('SELECT * FROM omnixat_extraction.create_csv_draft_amount(%s,%s,%s,%s,%s,%s,%s)',
                (self.org,self.task.evidence_id,second_job,plan.source_cell.field_name,plan.source_cell.row,plan.source_cell.column,str(self.user)))
            second_expense = self.owner.execute('SELECT * FROM omnixat_extraction.create_csv_expense_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (self.org,self.task.evidence_id,second_job,plan.source_cell.field_name,plan.source_cell.row,plan.source_cell.column,
                 plan.period_id,plan.context.expense_account_id,plan.context.accounting_date,'GBP',str(self.user))).fetchone()[1]
        self.owner.execute('UPDATE omnixat.agent_job_expense_effects SET expense_id=%s WHERE job_id=%s',(second_expense,job))
        with self.assertRaises(EvidenceNotEligible):
            self.expense_summary(token,job,lease)
        self.owner.execute('UPDATE omnixat.agent_job_expense_effects SET expense_id=%s WHERE job_id=%s',(first.expense_id,job))
        self.assertEqual(self.expense_summary(token,job,lease).receipt,first)

    def journal_plan_setup(self):
        token,job,lease,expense_plan = self.expense_execution_setup()
        receipt = self.execute_expense(token,job,lease)
        plan = JournalPreparationPlan(uuid4(),uuid4(),'personal_funds',uuid4())
        self.owner.execute("""INSERT INTO omnixat.expense_funding_sources
            (tenant_id,organisation_id,id,payer_id,funding_kind,eligible_for_drafts)
            VALUES (%s,%s,%s,%s,%s,true)""",(self.a,self.org,plan.funding_source_id,plan.payer_id,plan.funding_kind))
        self.owner.execute("""INSERT INTO omnixat.expense_counterpart_policy
            (tenant_id,organisation_id,funding_source_id,account_id,eligible_for_drafts)
            VALUES (%s,%s,%s,%s,true)""",(self.a,self.org,plan.funding_source_id,plan.counterpart_account_id))
        return token,job,lease,plan,receipt,expense_plan

    def save_journal_plan(self, token, job, lease, plan):
        return self.jobs.save_journal_plan(self.journal_plan_connection,token,self.a,job,lease,plan)

    def test_journal_intent_is_only_proposed_and_preserves_first_actor_after_reclaim(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        before = self.owner.execute('SELECT * FROM omnixat.agent_jobs WHERE id=%s',(job,)).fetchone()
        first = self.save_journal_plan(token,job,lease,plan)
        self.assertEqual((first.expense_id,first.plan,first.created_by),(expense.expense_id,plan,str(self.user)))
        self.assertEqual(self.save_journal_plan(token,job,lease,plan),first)
        self.assertEqual(self.jobs.get_journal_plan(token,self.a,job),first)
        self.assertEqual(self.owner.execute('SELECT * FROM omnixat.agent_jobs WHERE id=%s',(job,)).fetchone(),before)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.expense_funding_context WHERE tenant_id=%s',(self.a,)).fetchone(),(0,))
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(job,))
        second = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'journal-recovery','agent')",(second,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.a,second))
        token2 = self.token(sub='journal-recovery')
        with self.assertRaises(ValueError):
            self.save_journal_plan(token2,job,lease,plan)
        new = self.jobs.claim(token2,self.a,job)
        self.assertEqual(self.save_journal_plan(token2,job,new,plan),first)
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,lease,plan)

    def test_journal_intent_rechecks_expense_and_exact_funding_mapping(self):
        token,job,lease,plan,expense,ep = self.journal_plan_setup()
        for changed in [replace(plan,payer_id=uuid4()),replace(plan,funding_kind='business_funds'),
                        replace(plan,funding_source_id=uuid4()),replace(plan,counterpart_account_id=uuid4())]:
            with self.assertRaises(ValueError):
                self.save_journal_plan(token,job,lease,changed)
        for table,flag in [('expense_funding_sources','eligible_for_drafts'),
                           ('expense_counterpart_policy','eligible_for_drafts'),
                           ('expense_accounting_periods','open_for_drafts'),('expense_account_policy','eligible_for_drafts')]:
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=false WHERE tenant_id=%s',(self.a,))
            with self.assertRaises(ValueError):
                self.save_journal_plan(token,job,lease,plan)
            self.owner.execute('UPDATE omnixat.'+table+' SET '+flag+'=true WHERE tenant_id=%s',(self.a,))
        self.owner.execute("""INSERT INTO omnixat.expense_counterpart_policy VALUES (%s,%s,%s,%s,true)""",
                           (self.a,self.org,plan.funding_source_id,ep.context.expense_account_id))
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,lease,replace(plan,counterpart_account_id=ep.context.expense_account_id))
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_journal_plans WHERE job_id=%s',(job,)).fetchone(),(0,))
        first = self.save_journal_plan(token,job,lease,plan)
        self.owner.execute("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'")
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,lease,plan)
        self.assertEqual(self.jobs.get_journal_plan(token,self.a,job),first)  # historical intent, not eligibility

    def test_journal_intent_conflict_and_parent_digest_corruption_preserve_original(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        first = self.save_journal_plan(token,job,lease,plan)
        account = uuid4()
        self.owner.execute('INSERT INTO omnixat.expense_counterpart_policy VALUES (%s,%s,%s,%s,true)',
                           (self.a,self.org,plan.funding_source_id,account))
        with self.assertRaises(CreationConflict):
            self.save_journal_plan(token,job,lease,replace(plan,counterpart_account_id=account))
        self.assertEqual(self.jobs.get_journal_plan(token,self.a,job),first)
        self.owner.execute('UPDATE omnixat.agent_job_journal_plans SET expense_plan_digest=%s WHERE job_id=%s',(b'x'*32,job))
        with self.assertRaises(CreationConflict):
            self.save_journal_plan(token,job,lease,plan)
        self.owner.execute('UPDATE omnixat.agent_job_journal_plans SET plan_digest=%s WHERE job_id=%s',(b'y'*32,job))
        with self.assertRaises(CreationConflict):
            self.jobs.get_journal_plan(token,self.a,job)

    def test_journal_intent_scopes_membership_tenant_and_terminal_claims(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        for invalid in [self.token(scope='records:read'),self.token(scope='records:write')]:
            with self.assertRaises(PermissionError):
                self.save_journal_plan(invalid,job,lease,plan)
        with self.assertRaises(AuthenticationError):
            self.jobs.save_journal_plan(self.journal_plan_connection,token,self.b,job,lease,plan)
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.b,self.user))
        with self.assertRaises(KeyError):
            self.jobs.get_journal_plan(token,self.b,job)
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,uuid4(),plan)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        with self.assertRaises(PermissionError):
            self.save_journal_plan(token,job,lease,plan)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor',revoked_at=now() WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        with self.assertRaises(AuthenticationError):
            self.save_journal_plan(token,job,lease,plan)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=NULL WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        self.jobs.cancel(token,self.a,job)
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,lease,plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_journal_plans WHERE job_id=%s',(job,)).fetchone(),(0,))

    def test_journal_intent_concurrent_retries_and_receipt_failure_are_atomic(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        with patch('omnixat_core.job_journal_plans_postgres._receipt',side_effect=RuntimeError('fictional failure')):
            with self.assertRaises(RuntimeError):
                self.save_journal_plan(token,job,lease,plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_journal_plans WHERE job_id=%s',(job,)).fetchone(),(0,))
        barrier = Barrier(2)
        def save():
            with psycopg.connect(self.job_auth_dsn,autocommit=True) as auth, psycopg.connect(self.job_data_dsn,autocommit=True) as data, psycopg.connect(self.job_journal_plan_dsn,autocommit=True) as gate:
                service = AuthenticatedJobStore(auth,data,self.verifier)
                barrier.wait(timeout=5)
                return service.save_journal_plan(gate,token,self.a,job,lease,plan)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b = [f.result(timeout=10) for f in [pool.submit(save),pool.submit(save)]]
        self.assertEqual(a,b)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_journal_plans WHERE job_id=%s',(job,)).fetchone(),(1,))
        self.assertEqual(self.journal_plan_connection.execute("SELECT current_setting('omnixat.tenant_id',true)").fetchone(),('',))

    def test_journal_intent_requires_dedicated_grants_and_rejects_missing_expense(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.journal_plan_connection.execute('SELECT * FROM omnixat.agent_job_journal_plans')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.job_connection.execute('DELETE FROM omnixat.agent_job_journal_plans')
        with self.assertRaises(PermissionError):
            self.jobs.save_journal_plan(self.gate_connection,token,self.a,job,lease,plan)
        self.owner.execute('DELETE FROM omnixat.agent_job_expense_effects WHERE job_id=%s',(job,))
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,lease,plan)

    def test_journal_intent_expiry_during_insert_rolls_back_new_plan(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        self.owner.execute("""CREATE FUNCTION omnixat.fictional_slow_journal_plan() RETURNS trigger LANGUAGE plpgsql
            AS $$ BEGIN PERFORM pg_sleep(1.1); RETURN NEW; END; $$""")
        self.owner.execute('CREATE TRIGGER fictional_slow_journal_plan BEFORE INSERT ON omnixat.agent_job_journal_plans FOR EACH ROW EXECUTE FUNCTION omnixat.fictional_slow_journal_plan()')
        self.addCleanup(self.owner.execute,'DROP FUNCTION omnixat.fictional_slow_journal_plan() CASCADE')
        self.owner.execute("UPDATE omnixat.agent_jobs SET lease_until=clock_timestamp()+interval '1 second' WHERE id=%s",(job,))
        with self.assertRaises(ValueError):
            self.save_journal_plan(token,job,lease,plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_journal_plans WHERE job_id=%s',(job,)).fetchone(),(0,))

    def test_journal_intent_reauthenticates_after_recovering_parent_plans(self):
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        original = self.jobs.get_expense_plan
        def revoke_after_plan(*args):
            saved = original(*args)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
            return saved
        with patch.object(self.jobs,'get_expense_plan',side_effect=revoke_after_plan):
            with self.assertRaises(AuthenticationError):
                self.save_journal_plan(token,job,lease,plan)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.agent_job_journal_plans WHERE job_id=%s',(job,)).fetchone(),(0,))

    def test_journal_intent_rls_historical_read_and_composite_binding(self):
        from omnixat_core.postgres import _tenant_transaction
        token,job,lease,plan,expense,_ = self.journal_plan_setup()
        first = self.save_journal_plan(token,job,lease,plan)
        for tenant,expected in [(self.b,[]),(self.a,[(first.job_id,)])]:
            with _tenant_transaction(self.job_connection,tenant,tables_required=('agent_job_journal_plans',)):
                self.assertEqual(self.job_connection.execute('SELECT job_id FROM omnixat.agent_job_journal_plans').fetchall(),expected)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_journal_plans SET organisation_id=%s WHERE job_id=%s',(uuid4(),job))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.owner.execute('UPDATE omnixat.agent_job_journal_plans SET expense_id=%s WHERE job_id=%s',(uuid4(),job))
        self.jobs.cancel(token,self.a,job)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        self.assertEqual(self.jobs.get_journal_plan(self.token(scope='records:read'),self.a,job),first)
        for table in ['expense_funding_context','expense_journal_drafts','expense_journal_review_decisions']:
            self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.'+table+' WHERE tenant_id=%s',(self.a,)).fetchone(),(0,))
