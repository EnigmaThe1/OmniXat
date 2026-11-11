"""Fictional, human bookkeeping observations. Never statutory approval."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_journal_observations import JournalObservationFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.customer_bookkeeping_observations import FUNCTION, record_observation
from omnixat_core.customer_journal_observations import FUNCTION as READ, read_observations


class BookkeepingObservationFixture(JournalObservationFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.bookkeeping_role=cls.role+'_bookkeeping';password=uuid4().hex
        cls.bookkeeping_dsn=make_conninfo(cls.admin_dsn,dbname=cls.database,user=cls.bookkeeping_role,password=password)
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(cls.bookkeeping_role),sql.Literal(password)))
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.bookkeeping_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.bookkeeping_role)))
        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_journal_decisions TO {}').format(sql.Identifier(cls.bookkeeping_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+FUNCTION+' TO {}').format(sql.Identifier(cls.bookkeeping_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def writes():
            with psycopg.connect(self.bookkeeping_dsn,autocommit=True) as connection:yield connection
        self.bookkeeping_writes=writes;self.app=self.bookkeeping_app()
        self.client=TestClient(self.app,base_url=self.origin);self.addCleanup(self.client.close)

    def bookkeeping_app(self,enabled=True):
        return create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            expense_draft_connection_factory=self.draft_connections,
            expense_journal_read_connection_factory=self.journal_factories['inspect'],
            expense_journal_preview_connection_factory=self.journal_factories['preview'],
            expense_journal_write_connection_factory=self.journal_factories['create'],
            expense_funding_write_connection_factory=self.fund_writes,
            journal_observation_connection_factory=self.observation_reads,
            bookkeeping_observation_connection_factory=self.bookkeeping_writes if enabled else None)

    def prepare_bookkeeping(self):
        self.prepare_observations(0);self.document={'snapshot_sha256':self.snapshot,'decision':'changes_requested'}

    def record_observation(self,document=None,headers=None,url=None):
        return self.client.post(url or self.observation_url,json=self.document if document is None else document,
            headers=self.headers()|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))


class CustomerBookkeepingObservationTests(BookkeepingObservationFixture):
    def test_receipt_inspection_immutable_choice_and_no_ledger_change(self):
        self.prepare_bookkeeping();result=self.record_observation();self.assertEqual(result.status_code,200,result.text)
        receipt=result.json()['data'];self.assertEqual(receipt['reviewer_id'],str(self.user));self.assertEqual(receipt['decision'],'changes_requested')
        self.assertEqual(receipt['snapshot_sha256'],self.snapshot);self.assertEqual(receipt['journal_id'],self.journal['id'])
        self.assertEqual(self.record_observation().json()['data'],receipt)
        self.assertEqual(self.observations().json()['data']['items'][0],{k:receipt[k] for k in ('reviewer_id','decision','recorded_at')})
        conflict=self.record_observation(self.document|{'decision':'reviewed'});self.assertEqual(conflict.status_code,409,conflict.text)
        self.assertEqual(conflict.json()['error']['code'],'bookkeeping_observation_conflict')
        self.assertEqual(self.rows('expense_journal_review_decisions'),1);self.assertEqual(self.rows('expense_journal_drafts'),1)
        self.assertIn('no-store',result.headers['cache-control'])
        other=uuid4();self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-other-reviewer','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        second=self.record_observation(self.document|{'decision':'reviewed'},headers=self.headers(sub='fictional-other-reviewer')|{'X-OmniXat-Expected-Actor':str(other)})
        self.assertEqual(second.status_code,200,second.text);self.assertEqual(second.json()['data']['reviewer_id'],str(other))
        self.assertEqual(self.rows('expense_journal_review_decisions'),2)

    def test_concurrent_receipt_reuse_and_stale_snapshot_no_insert(self):
        self.prepare_bookkeeping();result=self.record_observation(self.document|{'snapshot_sha256':'0'*64})
        self.assertEqual(result.status_code,409,result.text);self.assertEqual(result.json()['error']['code'],'journal_snapshot_changed')
        self.assertEqual(self.rows('expense_journal_review_decisions'),0)
        with ThreadPoolExecutor(max_workers=2) as workers:responses=list(workers.map(lambda _:self.record_observation(),range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200]);self.assertEqual(responses[0].json()['data'],responses[1].json()['data'])
        self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-updated-snapshot' WHERE id=%s",(self.journal['id'],))
        self.assertEqual(self.record_observation().status_code,409);self.assertEqual(self.rows('expense_journal_review_decisions'),1)

    def test_tenant_evidence_draft_binding_and_current_policy_gates(self):
        self.prepare_bookkeeping();self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.observation_url.replace(self.a,self.b),self.observation_url.replace(self.evidence,str(uuid4())),
                    self.observation_url.replace(str(self.org),str(uuid4())),self.observation_url.replace(str(self.saved.id),str(uuid4()))]:
            self.assertEqual(self.record_observation(url=url).status_code,404)
        self.owner.execute('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,))
        self.assertEqual(self.record_observation().status_code,404)
        self.owner.execute('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=true WHERE account_id=%s',(self.counterpart,))
        self.verdict('blocked');self.assertEqual(self.record_observation().status_code,404)
        self.assertEqual(self.rows('expense_journal_review_decisions'),0)

    def test_scopes_viewer_human_revocation_and_expected_actor(self):
        self.prepare_bookkeeping()
        self.assertEqual(self.record_observation(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.record_observation(headers=self.headers(scope='records:read evidence:read')).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.record_observation().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            with self.bookkeeping_writes() as connection,self.assertRaises(PermissionError):
                record_observation(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,self.document,expected_actor=self.user)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.record_observation().status_code,403);self.assertEqual(self.rows('expense_journal_review_decisions'),0)

    def test_strict_body_disabled_write_and_separate_reader_writer_grants(self):
        self.prepare_bookkeeping()
        for doc in [{},self.document|{'decision':'approve'},self.document|{'decision':None},self.document|{'snapshot_sha256':'A'*64},
                    self.document|{'amount':'12'},self.document|{'reviewer_id':str(self.user)},self.document|{'approved_at':None}]:
            self.assertEqual(self.record_observation(doc).status_code,422,doc)
        self.assertEqual(self.record_observation(url=self.observation_url+'?approve=true').status_code,400)
        with TestClient(self.bookkeeping_app(False),base_url=self.origin) as client:
            self.assertEqual(client.post(self.observation_url,json=self.document,headers=self.headers()).status_code,405)
        token=self.token(scope=SCOPES)
        with self.bookkeeping_writes() as connection:
            record_observation(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id,self.document,expected_actor=self.user)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):connection.execute('SELECT * FROM omnixat.expense_journal_review_decisions')
        self.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_journal_reviews TO {}').format(sql.Identifier(self.bookkeeping_role)))
        self.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+READ+' TO {}').format(sql.Identifier(self.bookkeeping_role)))
        try:
            with self.bookkeeping_writes() as connection,self.assertRaises(PermissionError):
                record_observation(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id,self.document,expected_actor=self.user)
            with self.bookkeeping_writes() as connection,self.assertRaises(PermissionError):
                read_observations(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id,snapshot_sha256=self.snapshot)
        finally:
            self.owner.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION '+READ+' FROM {}').format(sql.Identifier(self.bookkeeping_role)))
            self.owner.execute(sql.SQL('REVOKE USAGE ON SCHEMA omnixat_customer_journal_reviews FROM {}').format(sql.Identifier(self.bookkeeping_role)))

    def test_non_bypassrls_writer_chain(self):
        self.prepare_bookkeeping();functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner) FROM pg_proc p
          JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_journal_decisions')""").fetchall()
        def restore():
            for function,owner in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        for grant in ['USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_journal_decisions','USAGE ON SCHEMA omnixat',
                      'SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction','INSERT ON omnixat.expense_journal_review_decisions',
                      'UPDATE ON omnixat.identities,omnixat.memberships,omnixat.csv_expense_drafts,omnixat.expense_journal_drafts,omnixat_extraction.active_scan_policy,omnixat.expense_accounting_periods,omnixat.expense_account_policy,omnixat.evidence_quarantine,omnixat.evidence_registrations,omnixat.evidence_scan_claims,omnixat.expense_funding_sources,omnixat.expense_funding_context,omnixat.expense_counterpart_policy,omnixat.evidence_draft_amounts,omnixat.csv_extraction_results']:
            self.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        result=self.record_observation();self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.record_observation().json()['data'],result.json()['data'])

    def test_gate_locks_hold_through_commit(self):
        from omnixat_core.postgres import _tenant_transaction
        self.prepare_bookkeeping()
        with self.bookkeeping_writes() as connection:
            with _tenant_transaction(connection,UUID(self.a),write=True,tables_required=('expense_journal_review_decisions',)):
                connection.execute('SELECT * FROM omnixat_customer_journal_decisions.record_observation(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (self.issuer,self.subject,self.iat,self.org,self.evidence,self.saved.id,self.user,bytes.fromhex(self.snapshot),'reviewed')).fetchone()
                for query,params in [
                    ('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,)),
                    ('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user)),
                    ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'",()),
                    ('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s',(self.a,)),
                    ('UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE id=%s',(self.personal_source,)),
                    ('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,)),
                    ("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed-author' WHERE id=%s",(self.journal['id'],)),
                    ("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','blocked',now() FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s",(self.a,self.evidence))]:
                    with self.subTest(query=query),self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='40ms'");self.owner.execute(query,params)
        self.assertEqual(self.rows('expense_journal_review_decisions'),1)
