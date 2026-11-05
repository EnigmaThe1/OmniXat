from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql

from omnixat_core.access import Principal
from omnixat_core.evidence_postgres import EvidenceConflict, get_evidence, register_evidence
from omnixat_core.postgres import tenant_records
from test_postgres import PostgresFixture


class EvidencePostgresTests(PostgresFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner.execute(sql.SQL("GRANT SELECT, INSERT ON omnixat.evidence_registrations TO {}")
                          .format(sql.Identifier(cls.role)))

    def setUp(self):
        super().setUp()
        self.metadata = {
            "content_sha256": sha256(b"Fictional evidence fixture").hexdigest(),
            "media_type": "application/pdf",
            "byte_size": 26,
        }

    def register(self, **changes):
        return register_evidence(self.runtime, self.actor, self.a, self.org, **(self.metadata | changes))

    def test_replay_keeps_original_registration_and_registrar(self):
        created = self.register()
        editor = Principal("another-editor", self.a, "editor")
        with psycopg.connect(self.runtime_dsn, autocommit=True) as db:
            replayed = register_evidence(db, editor, self.a, self.org, **self.metadata)
            viewed = get_evidence(db, Principal("viewer", self.a, "viewer"), self.a, self.org, created.id)
        self.assertEqual(created, replayed)
        self.assertEqual(created, viewed)
        self.assertEqual(created.registered_by, self.actor.user_id)

    def test_same_digest_with_conflicting_metadata_does_not_change_original(self):
        created = self.register()
        for changed in ({"byte_size": 20}, {"media_type": "image/png"}):
            with self.subTest(changed=changed), self.assertRaises(EvidenceConflict):
                self.register(**changed)
        self.assertEqual(self.register(), created)

    def test_deduplication_is_scoped_to_tenant_and_organisation(self):
        first = self.register()
        with tenant_records(self.runtime, self.actor, self.a, write=True) as records:
            second_org = records.create_organisation("Other fictional organisation")["id"]
        with tenant_records(self.runtime, self.other, self.b, write=True) as records:
            third_org = records.create_organisation("Other fictional tenant organisation")["id"]
        second = register_evidence(self.runtime, self.actor, self.a, second_org, **self.metadata)
        third = register_evidence(self.runtime, self.other, self.b, third_org, **self.metadata)
        self.assertEqual(len({first.id, second.id, third.id}), 3)
        for actor, tenant, organisation in ((self.actor, self.a, second_org), (self.other, self.b, self.org)):
            with self.assertRaises(KeyError):
                get_evidence(self.runtime, actor, tenant, organisation, first.id)
        with self.assertRaises(KeyError):
            register_evidence(self.runtime, self.other, self.b, self.org, **self.metadata)

    def test_untrusted_actor_and_bad_metadata_cannot_register(self):
        for actor in (
            Principal("viewer", self.a, "viewer"),
            Principal("agent", self.a, "editor", actor_kind="agent"),
            Principal("staff", self.a, "owner", staff_role="platform_owner"),
            Principal("records-bearer", self.a, "editor", api_scopes=frozenset({"records:write"})),
        ):
            with self.subTest(actor=actor.user_id), self.assertRaises(PermissionError):
                register_evidence(self.runtime, actor, self.a, self.org, **self.metadata)
        for changes in ({"content_sha256": "not-a-hash"}, {"byte_size": True},
                        {"byte_size": 20 * 1024 * 1024 + 1}, {"media_type": "text/html"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.register(**changes)
        with self.runtime.transaction():
            self.runtime.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (str(self.a),))
            self.assertEqual(self.runtime.execute("SELECT count(*) FROM omnixat.evidence_registrations")
                             .fetchone(), (0,))

    def test_database_enforces_rls_composite_fk_and_append_only_grants(self):
        self.register()
        self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.evidence_registrations").fetchall(), [])
        with self.runtime.transaction():
            self.runtime.execute("SELECT set_config('omnixat.tenant_id',%s,true)", (str(self.b),))
            self.assertEqual(self.runtime.execute("SELECT * FROM omnixat.evidence_registrations").fetchall(), [])
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                self.runtime.execute("""
                    INSERT INTO omnixat.evidence_registrations
                      (tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by)
                    VALUES (%s,%s,%s,%s,'application/pdf',1,'fixture')
                """, (self.b, uuid4(), self.org, bytes(32)))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.runtime.execute("DELETE FROM omnixat.evidence_registrations")

    def test_concurrent_registration_replays_one_row(self):
        barrier = Barrier(2, timeout=5)

        def attempt():
            with psycopg.connect(self.runtime_dsn, autocommit=True) as db:
                barrier.wait()
                return register_evidence(db, self.actor, self.a, self.org, **self.metadata)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [pool.submit(attempt) for _ in range(2)]
            self.assertEqual(first.result(timeout=10), second.result(timeout=10))
