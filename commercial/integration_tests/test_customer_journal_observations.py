"""Read-only, exact-snapshot journal review history with fictional fixtures."""
from contextlib import contextmanager
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_expense_journals import ExpenseJournalFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.customer_journal_observations import FUNCTION, read_observations


class JournalObservationFixture(ExpenseJournalFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.observation_role=cls.role+'_observations';password=uuid4().hex
        cls.observation_dsn=make_conninfo(cls.admin_dsn,dbname=cls.database,user=cls.observation_role,password=password)
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(cls.observation_role),sql.Literal(password)))
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.observation_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.observation_role)))
        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_journal_reviews TO {}').format(sql.Identifier(cls.observation_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+FUNCTION+' TO {}').format(sql.Identifier(cls.observation_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def reads():
            with psycopg.connect(self.observation_dsn,autocommit=True) as connection:yield connection
        self.observation_reads=reads;self.app=self.observation_app()
        self.client=TestClient(self.app,base_url=self.origin);self.addCleanup(self.client.close)

    def observation_app(self,enabled=True):
        return create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            expense_draft_connection_factory=self.draft_connections,
            expense_journal_read_connection_factory=self.journal_factories['inspect'],
            expense_journal_preview_connection_factory=self.journal_factories['preview'],
            expense_journal_write_connection_factory=self.journal_factories['create'],
            expense_funding_write_connection_factory=self.fund_writes,
            journal_observation_connection_factory=self.observation_reads if enabled else None)

    def prepare_observations(self,count=1):
        self.prepare_journal();self.assertEqual(self.save_journal().status_code,201)
        self.journal=self.inspect_journal().json()['data']['journal'];self.snapshot=self.journal['snapshot_sha256']
        self.observation_url=self.journal_url+'-observations'
        for index in range(count):self.add_observation(f'fictional-reviewer-{index:03d}','reviewed' if index%2 else 'changes_requested')

    def add_observation(self,reviewer,decision='reviewed',snapshot=None):
        self.owner.execute('INSERT INTO omnixat.expense_journal_review_decisions VALUES (%s,%s,%s,%s,%s,%s,DEFAULT)',
            (self.a,self.org,self.journal['id'],bytes.fromhex(snapshot or self.snapshot),reviewer,decision))

    def observations(self,params=None,headers=None,url=None):
        return self.client.get(url or self.observation_url,params={'snapshot_sha256':self.snapshot} if params is None else params,
            headers=self.headers()|(headers or {}))


class CustomerJournalObservationTests(JournalObservationFixture):
    def test_attributed_readonly_history_bound_to_saved_snapshot_and_viewer(self):
        self.prepare_observations(2);before=self.rows('expense_journal_review_decisions')
        self.add_observation('fictional-other-snapshot',snapshot='0'*64)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        response=self.observations();self.assertEqual(response.status_code,200,response.text);data=response.json()['data']
        self.assertEqual([x['decision'] for x in data['items']],['changes_requested','reviewed'])
        self.assertEqual([x['reviewer_id'] for x in data['items']],['fictional-reviewer-000','fictional-reviewer-001'])
        self.assertEqual(data['journal_id'],self.journal['id']);self.assertEqual(data['snapshot_sha256'],self.snapshot)
        self.assertFalse(data['has_more']);self.assertIsNone(data['next_after_reviewer'])
        self.assertEqual(self.rows('expense_journal_review_decisions'),before+1)
        self.assertIn('no-store',response.headers['cache-control']);self.assertNotIn(self.original.decode(),response.text)
        self.assertEqual(self.client.post(self.observation_url,json={},headers=self.headers()).status_code,405)

    def test_bounded_cursor_pages_empty_history_and_stale_snapshot(self):
        self.prepare_observations(0);data=self.observations().json()['data'];self.assertEqual(data['items'],[])
        for i in range(23):self.add_observation(f'fictional-reviewer-{i:03d}')
        first=self.observations().json()['data'];self.assertEqual(len(first['items']),20);self.assertTrue(first['has_more'])
        second=self.observations({'snapshot_sha256':self.snapshot,'after_reviewer':first['next_after_reviewer']}).json()['data']
        self.assertEqual(len(second['items']),3);self.assertFalse(second['has_more']);self.assertIsNone(second['next_after_reviewer'])
        self.assertFalse({x['reviewer_id'] for x in first['items']} & {x['reviewer_id'] for x in second['items']})
        result=self.observations({'snapshot_sha256':'0'*64});self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(result.json()['error']['code'],'journal_snapshot_changed')

    def test_tenant_evidence_draft_binding_and_current_source_gates(self):
        self.prepare_observations();self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.b,self.user))
        for url in [self.observation_url.replace(self.a,self.b),self.observation_url.replace(self.evidence,str(uuid4())),
                    self.observation_url.replace(str(self.org),str(uuid4())),self.observation_url.replace(str(self.saved.id),str(uuid4()))]:
            self.assertEqual(self.observations(url=url).status_code,404)
        self.owner.execute('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,))
        self.assertEqual(self.observations().status_code,404)
        self.assertEqual(self.rows('expense_journal_review_decisions'),1)

    def test_fresh_scopes_human_identity_revocation_and_reader_cleanup(self):
        self.prepare_observations();token=self.token(scope=SCOPES)
        for scope in ['records:read','evidence:read','filings:approve']:
            self.assertEqual(self.observations(headers=self.headers(scope=scope)).status_code,403)
        with self.observation_reads() as connection:
            read_observations(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id,snapshot_sha256=self.snapshot)
            for setting in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(setting,)).fetchone()[0],('',None))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):connection.execute('SELECT * FROM omnixat.expense_journal_review_decisions')
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            with self.observation_reads() as connection,self.assertRaises(PermissionError):
                read_observations(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id,snapshot_sha256=self.snapshot)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.observations().status_code,403)

    def test_strict_query_disabled_capability_and_mixed_role_rejection(self):
        self.prepare_observations()
        for params in [{},{'snapshot_sha256':'A'*64},{'snapshot_sha256':self.snapshot,'after_reviewer':''},
                       {'snapshot_sha256':self.snapshot,'after_reviewer':'x'*201},
                       {'snapshot_sha256':self.snapshot,'approve':'true'},
                       [('snapshot_sha256',self.snapshot),('snapshot_sha256',self.snapshot)]]:
            self.assertEqual(self.observations(params).status_code,400,params)
        with TestClient(self.observation_app(False),base_url=self.origin) as client:
            self.assertEqual(client.get(self.observation_url,headers=self.headers()).status_code,404)
        self.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_extraction TO {}').format(sql.Identifier(self.observation_role)))
        try:
            with self.observation_reads() as connection,self.assertRaises(PermissionError):
                read_observations(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,snapshot_sha256=self.snapshot)
        finally:self.owner.execute(sql.SQL('REVOKE USAGE ON SCHEMA omnixat_extraction FROM {}').format(sql.Identifier(self.observation_role)))

    def test_non_bypassrls_function_owner_chain(self):
        self.prepare_observations()
        functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner) FROM pg_proc p
          JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_journal_reviews')""").fetchall()
        def restore():
            for function,owner in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        for grant in ['USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_journal_reviews','USAGE ON SCHEMA omnixat','SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction']:
            self.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        result=self.observations();self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['data']['items'][0]['reviewer_id'],'fictional-reviewer-000')
