from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import psycopg

from omnixat_core.access import Principal
from omnixat_core.postgres import CreationConflict, tenant_records
from test_postgres import PostgresFixture


class CreationReceiptTests(PostgresFixture):
    def test_key_scope_is_workspace_actor_and_operation(self):
        key = 'fictional-operation'
        peer = Principal('fictional-peer', self.a, 'editor')
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            org = records.create_organisation('Fictional A', idempotency_key=key)
            note = records.create_note(org['id'], 'Fictional note', idempotency_key=key)
        with tenant_records(self.runtime, peer, self.a, write=True) as records:
            peer_org = records.create_organisation('Fictional peer', idempotency_key=key)
        with tenant_records(self.runtime, self.other, self.b, write=True) as records:
            other_org = records.create_organisation('Fictional B', idempotency_key=key)
        self.assertEqual(len({org['id'], note['id'], peer_org['id'], other_org['id']}), 4)

    def test_note_key_binds_parent_and_exact_text(self):
        key = 'fictional-note'
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            other = records.create_organisation('Fictional second parent')
            first = records.create_note(self.org, 'Exact text', idempotency_key=key)
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            self.assertEqual(records.create_note(self.org, 'Exact text', idempotency_key=key), first)
            for parent, body in ((other['id'], 'Exact text'), (self.org, 'Exact text ')):
                with self.assertRaises(CreationConflict):
                    records.create_note(parent, body, idempotency_key=key)

    def test_rollback_releases_key_and_result(self):
        key = 'fictional-retry'
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
                discarded = records.create_organisation('Interrupted work', idempotency_key=key)
                raise RuntimeError('interrupted')
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            with self.assertRaises(KeyError):
                records.get_organisation(discarded['id'])
            persisted = records.create_organisation('Replacement work', idempotency_key=key)
        self.assertNotEqual(discarded['id'], persisted['id'])

    def test_concurrent_replay_waits_and_returns_one_committed_result(self):
        key = 'fictional-race'
        waiting = Queue()

        def contender():
            with psycopg.connect(self.runtime_dsn, autocommit=True) as db:
                with tenant_records(db, self.actor, self.a, write=True) as records:
                    waiting.put(db.info.backend_pid)
                    return records.create_organisation('Fictional concurrent', idempotency_key=key)

        with ThreadPoolExecutor(max_workers=1) as executor:
            with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
                first = records.create_organisation('Fictional concurrent', idempotency_key=key)
                future = executor.submit(contender)
                pid = waiting.get(timeout=2)
                deadline = monotonic() + .65
                while monotonic() < deadline:
                    state = self.owner.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)).fetchone()
                    if state == ('Lock',):
                        break
                    sleep(.01)
                else:
                    self.fail('Concurrent request did not wait on the uncommitted reservation')
            self.assertEqual(future.result(timeout=3), first)
        self.assertEqual(self.owner.execute(
            "SELECT count(*) FROM omnixat.organisations WHERE tenant_id=%s AND display_name=%s",
            (self.a, 'Fictional concurrent')).fetchone(), (1,))

    def test_unkeyed_creations_have_distinct_results_and_minimal_receipts(self):
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            first = records.create_organisation('Fictional identical name')
            second = records.create_organisation('Fictional identical name')
        self.assertNotEqual(first['id'], second['id'])
        rows = self.owner.execute("""SELECT actor_id, operation, key_digest, payload_digest
            FROM omnixat.record_creations WHERE tenant_id=%s AND organisation_id IN (%s,%s)""",
            (self.a, first['id'], second['id'])).fetchall()
        self.assertEqual(rows, [(self.actor.user_id, 'organisation.create', None, None)] * 2)

    def test_receipts_hidden_outside_actor_and_tenant_and_not_mutable(self):
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            records.create_organisation('Fictional audit', idempotency_key='fictional-audit')
        self.assertEqual(self.runtime.execute("SELECT count(*) FROM omnixat.record_creations").fetchone(), (0,))
        with tenant_records(self.runtime, Principal('fictional-peer', self.a, 'editor'), self.a, write=True) as records:
            records.create_organisation('Fictional peer audit')
            self.assertEqual(self.runtime.execute(
                "SELECT DISTINCT actor_id FROM omnixat.record_creations").fetchall(), [('fictional-peer',)])
        for query in ("DELETE FROM omnixat.record_creations", "UPDATE omnixat.record_creations SET actor_id='tampered'"):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.runtime.execute(query)

    def test_unfulfilled_or_cross_tenant_reservation_cannot_commit(self):
        for missing in (uuid4(), self.org):
            with self.subTest(missing=missing), self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with tenant_records(self.runtime, self.other, self.b, write=True):
                    self.runtime.execute("SELECT set_config('omnixat.record_actor', %s, true)", (self.other.user_id,))
                    self.runtime.execute("""INSERT INTO omnixat.record_creations
                        (tenant_id, actor_id, operation, organisation_id)
                        VALUES (%s,%s,'organisation.create',%s)""", (self.b, self.other.user_id, missing))
