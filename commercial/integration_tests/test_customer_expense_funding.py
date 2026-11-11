"""Fictional explicit funding declarations; no bank connection or money movement."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_expense_drafts import CustomerExpenseDraftFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.customer_expense_funding import read_funding, record_funding

READ='omnixat_customer_funding.read_funding(text,text,bigint,uuid,uuid,uuid)'
WRITE='omnixat_customer_funding.record_funding(text,text,bigint,uuid,uuid,uuid,uuid,uuid,uuid)'


class ExpenseFundingFixture(CustomerExpenseDraftFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for label,function in [('fund_read',READ),('fund_write',WRITE)]:
            role=cls.role+'_'+label;password=uuid4().hex
            setattr(cls,label+'_role',role);setattr(cls,label+'_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
            cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_funding TO {}').format(sql.Identifier(role)))
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+function+' TO {}').format(sql.Identifier(role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def reads():
            with psycopg.connect(self.fund_read_dsn,autocommit=True) as connection:yield connection
        @contextmanager
        def writes():
            with psycopg.connect(self.fund_write_dsn,autocommit=True) as connection:yield connection
        self.fund_reads,self.fund_writes=reads,writes
        self.app=self.funding_app()
        self.client=TestClient(self.app,base_url=self.origin);self.addCleanup(self.client.close)

    def funding_app(self,write=True,read=True):
        return create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            expense_draft_connection_factory=self.draft_connections,
            expense_funding_read_connection_factory=self.fund_reads if read else None,
            expense_funding_write_connection_factory=self.fund_writes if write else None)

    def prepare_funding(self):
        self.prepare()
        self.business_source,self.business_payer,self.personal_source,self.personal_payer=[uuid4() for _ in range(4)]
        for source,payer,kind in [(self.business_source,self.business_payer,'business_funds'),(self.personal_source,self.personal_payer,'personal_funds')]:
            self.owner.execute('INSERT INTO omnixat.expense_funding_sources VALUES (%s,%s,%s,%s,%s,true)',(self.a,self.org,source,payer,kind))
        self.document={'funding_source_id':str(self.personal_source),'payer_id':str(self.personal_payer)}
        self.funding_url=self.draft_url+'/'+str(self.saved.id)+'/funding'

    def read(self,headers=None,url=None):
        return self.client.get(url or self.funding_url,headers=self.headers()|(headers or {}))

    def record(self,document=None,headers=None,url=None):
        return self.client.post(url or self.funding_url,json=self.document if document is None else document,
            headers=self.headers()|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))


class ExpenseFundingTests(ExpenseFundingFixture):
    def test_choices_personal_declaration_receipt_and_inspection_without_effects(self):
        self.prepare_funding();result=self.read();self.assertEqual(result.status_code,200,result.text)
        data=result.json()['data'];self.assertIsNone(data['funding']);self.assertEqual(len(data['choices']),2)
        first=self.record();self.assertEqual(first.status_code,200,first.text)
        receipt=first.json()['data'];self.assertEqual(receipt['funding_kind'],'personal_funds')
        self.assertEqual(self.record().json()['data'],receipt)
        saved=self.read().json()['data']['funding']
        self.assertEqual(saved['recorded_by'],str(self.user));self.assertEqual(saved['payer_id'],str(self.personal_payer))
        self.assertTrue(saved['source_eligible']);self.assertEqual(self.rows('expense_funding_context'),1)
        self.assertEqual(self.rows('expense_journal_drafts'),0)
        self.assertIn('no-store',result.headers['cache-control']);self.assertNotIn(self.original.decode(),result.text)

    def test_concurrent_retry_conflicting_business_choice_and_wrong_payer(self):
        self.prepare_funding()
        self.assertEqual(self.record(self.document|{'payer_id':str(self.business_payer)}).status_code,404)
        with ThreadPoolExecutor(max_workers=2) as workers: responses=list(workers.map(lambda _:self.record(),range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200]);self.assertEqual(responses[0].json()['data'],responses[1].json()['data'])
        self.assertEqual(self.record({'funding_source_id':str(self.business_source),'payer_id':str(self.business_payer)}).status_code,409)
        self.assertEqual(self.read().json()['data']['funding']['funding_kind'],'personal_funds')
        self.assertEqual(self.rows('expense_funding_context'),1)

    def test_viewer_inspection_disabled_source_history_and_no_overwrite(self):
        self.prepare_funding();self.record()
        self.owner.execute('UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE tenant_id=%s AND id=%s',(self.a,self.personal_source))
        data=self.read().json()['data'];self.assertFalse(data['funding']['source_eligible'])
        self.assertNotIn(str(self.personal_source),[x['id'] for x in data['choices']])
        self.assertEqual(self.record().status_code,404)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        data=self.read().json()['data'];self.assertEqual(data['choices'],[]);self.assertEqual(data['funding']['payer_id'],str(self.personal_payer))
        self.assertEqual(self.record().status_code,403)
        self.assertEqual(self.rows('expense_funding_context'),1)

    def test_fresh_scopes_identity_expected_actor_and_revocation(self):
        self.prepare_funding()
        self.assertEqual(self.record(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.record(headers=self.headers(scope='records:read evidence:read')).status_code,403)
        self.assertEqual(self.read(headers=self.headers(scope='records:read')).status_code,403)
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            for factory,operation,args in [(self.fund_reads,read_funding,()),(self.fund_writes,record_funding,(self.document,))]:
                with factory() as connection,self.assertRaises(PermissionError):
                    operation(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,*args,
                        **({'expected_actor':self.user} if args else {}))
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.record().status_code,403);self.assertEqual(self.rows('expense_funding_context'),0)

    def test_tenant_evidence_draft_and_current_source_context_binding(self):
        self.prepare_funding()
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.funding_url.replace(self.a,self.b),self.funding_url.replace(self.evidence,str(uuid4())),
                    self.funding_url.replace(str(self.org),str(uuid4())),self.funding_url.replace(str(self.saved.id),str(uuid4()))]:
            self.assertEqual(self.read(url=url).status_code,404);self.assertEqual(self.record(url=url).status_code,404)
        self.owner.execute('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s',(self.a,))
        self.assertEqual(self.record().status_code,404);self.assertEqual(self.read().status_code,404)
        self.owner.execute('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=true WHERE tenant_id=%s',(self.a,))
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.record().status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.policy('fictional-v2');self.assertEqual(self.record().status_code,404)
        self.policy('fictional-v1');self.verdict('blocked');self.assertEqual(self.record().status_code,404)
        self.assertEqual(self.rows('expense_funding_context'),0)

    def test_strict_body_routes_and_bounded_choices(self):
        self.prepare_funding()
        for document in [{},{'payer_id':str(self.personal_payer)},self.document|{'amount':'12'},self.document|{'funding_kind':'business_funds'},
                         self.document|{'payer_id':None},self.document|{'payer_id':'00000000-0000-0000-0000-000000000000'}]:
            self.assertEqual(self.record(document).status_code,422,document)
        self.assertEqual(self.record(url=self.funding_url+'?approve=true').status_code,400)
        self.assertEqual(self.read(url=self.funding_url+'?limit=100').status_code,400)
        self.assertEqual(self.record(headers={'Origin':'https://other.example'}).status_code,403)
        for _ in range(21):self.owner.execute("INSERT INTO omnixat.expense_funding_sources VALUES (%s,%s,%s,%s,'business_funds',true)",(self.a,self.org,uuid4(),uuid4()))
        data=self.read().json()['data'];self.assertEqual(len(data['choices']),20);self.assertTrue(data['has_more'])
        with TestClient(self.funding_app(write=False,read=False),base_url=self.origin) as client:
            self.assertEqual(client.get(self.funding_url,headers=self.headers()).status_code,404)
            self.assertEqual(client.post(self.funding_url,json=self.document,headers=self.headers()).status_code,404)

    def test_separate_reader_writer_and_clean_transaction_context(self):
        self.prepare_funding()
        with self.fund_reads() as connection:
            read_funding(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id)
            for setting in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(setting,)).fetchone()[0],('',None))
            with self.assertRaises(PermissionError):record_funding(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,self.document,expected_actor=self.user)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):connection.execute('SELECT * FROM omnixat.expense_funding_context')
        with self.fund_writes() as connection,self.assertRaises(PermissionError):
            read_funding(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id)
        for dsn in [self.runtime_dsn,self.extract_dsn,self.owner_dsn]:
            with psycopg.connect(dsn,autocommit=True) as connection,self.assertRaises(PermissionError):
                record_funding(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,self.document,expected_actor=self.user)

    def test_complete_funding_read_write_chain_without_bypassrls_owner(self):
        self.prepare_funding()
        functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner)
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_funding')""").fetchall()
        def restore():
            for function,owner in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        for grant in ['USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_funding','USAGE ON SCHEMA omnixat',
                      'SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction','INSERT ON omnixat.expense_funding_context',
                      'UPDATE ON omnixat.identities,omnixat.memberships,omnixat.csv_expense_drafts,omnixat_extraction.active_scan_policy,omnixat.expense_accounting_periods,omnixat.expense_account_policy,omnixat.evidence_quarantine,omnixat.evidence_scan_claims,omnixat.expense_funding_sources']:
            self.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        self.assertIsNone(self.read().json()['data']['funding'])
        result=self.record();self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.record().json()['data'],result.json()['data'])
        self.assertEqual(self.read().json()['data']['funding']['recorded_by'],str(self.user))

    def test_write_holds_identity_policy_context_and_source_gates_until_commit(self):
        from uuid import UUID
        from omnixat_core.postgres import _tenant_transaction
        self.prepare_funding()
        with self.fund_writes() as connection:
            with _tenant_transaction(connection,UUID(self.a),write=True,tables_required=('expense_funding_context',)):
                connection.execute('SELECT * FROM '+WRITE.split('(')[0]+'(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (self.issuer,self.subject,self.iat,self.org,self.evidence,self.saved.id,self.user,self.personal_source,self.personal_payer)).fetchone()
                for query,params in [
                    ('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,)),
                    ('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user)),
                    ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'",()),
                    ('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s',(self.a,)),
                    ('UPDATE omnixat.expense_account_policy SET eligible_for_drafts=false WHERE tenant_id=%s',(self.a,)),
                    ('UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE tenant_id=%s AND id=%s',(self.a,self.personal_source)),
                    ("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','blocked',now() FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s",(self.a,self.evidence))
                ]:
                    with self.subTest(query=query),self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='40ms'")
                            self.owner.execute(query,params)
        self.assertEqual(self.read().json()['data']['funding']['funding_kind'],'personal_funds')
